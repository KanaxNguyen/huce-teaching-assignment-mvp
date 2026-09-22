from datetime import date
from sqlalchemy import select
from fastapi import HTTPException
import pytest
from app.db.session import Base, SessionLocal, engine
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Course,
    Lecturer,
    LecturerCourseCapability,
    NormalizedPreferenceDraft,
    OptimizationRun,
    Semester,
    ValidationIssue,
)
from app.optimization.solver import solve
from app.services.unassigned_diagnostics import (
    diagnose_unassigned_classes,
    get_candidate_analysis,
    get_unassigned_breakdown,
    update_resolution_status,
    override_lock_assignment,
)
from app.services.manual_assignment import apply_manual_assignment
from app.exporters.excel import export_latest
from test_phase3_solver import setup, capability


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_taxonomy_hard_availability_and_collision():
    """Verify diagnosis taxonomy correctly identifies HARD_AVAILABILITY_CONFLICT and TIMETABLE_COLLISION."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 2)
        capability(db, teacher_a, course)
        capability(db, teacher_b, course)

        # Teacher A is HARD unavailable on weekday 2, periods 1-3
        db.add(Constraint(
            semester_id=semester.id,
            name="Teacher A unavailable",
            constraint_type="UNAVAILABLE",
            hardness="hard",
            weight=1.0,
            lecturer_id=teacher_a.id,
            target={"weekday": 2, "periods": [1, 2, 3]},
            raw_text="Thứ 2 bận nghiên cứu",
            confirmed=True,
        ))
        db.commit()

        # Both groups on weekday 2, period 1-3
        groups[0].sessions[0].weekday = 2
        groups[0].sessions[0].start_period = 1
        groups[0].sessions[0].end_period = 3
        groups[0].sessions[0].weeks = list(range(1, 10))

        groups[1].sessions[0].weekday = 2
        groups[1].sessions[0].start_period = 1
        groups[1].sessions[0].end_period = 3
        groups[1].sessions[0].weeks = list(range(1, 10))
        db.commit()

        # Solve: only Teacher B is available for 1 class. The other class will be unassigned.
        run = solve(db, 2, False, semester.id)
        assert run.status in {"optimal", "feasible"}

        diagnostics = diagnose_unassigned_classes(db, semester.id, run.id)
        assert len(diagnostics) == 1
        diag = diagnostics[0]

        # The root cause must be diagnosed properly
        assert diag["root_cause"] in {"HARD_AVAILABILITY_CONFLICT", "GLOBAL_INFEASIBILITY", "TIMETABLE_COLLISION"}
        assert diag["root_cause_label"] != ""
        assert len(diag["recommended_actions"]) > 0


def test_bottleneck_detection_for_concurrent_classes():
    """Verify resource bottleneck calculation when concurrent classes exceed capable available lecturers."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 3)
        capability(db, teacher_a, course)
        # Teacher B does NOT have capability

        # All 3 groups on weekday 3, periods 4-6
        for g in groups:
            g.sessions[0].weekday = 3
            g.sessions[0].start_period = 4
            g.sessions[0].end_period = 6
            g.sessions[0].weeks = list(range(1, 10))
        db.commit()

        run = solve(db, 2, False, semester.id)
        diagnostics = diagnose_unassigned_classes(db, semester.id, run.id)
        assert len(diagnostics) == 2  # 1 assigned to teacher_a, 2 unassigned

        for diag in diagnostics:
            assert diag["root_cause"] == "GLOBAL_INFEASIBILITY"
            assert diag["bottleneck_details"] is not None
            assert diag["bottleneck_details"]["weekday"] == 3
            assert diag["bottleneck_details"]["overlapping_classes_count"] == 3
            assert diag["bottleneck_details"]["available_lecturers_count"] == 1
            assert diag["bottleneck_details"]["shortage"] == 2


def test_candidate_analysis_matrix_details():
    """Verify get_candidate_analysis returns all lecturers with Vietnamese labels and provenance."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 2)
        capability(db, teacher_a, course)
        # teacher_b has NO capability

        # Set sessions on weekday 2 periods 1-3
        groups[0].sessions[0].weekday = 2
        groups[0].sessions[0].start_period = 1
        groups[0].sessions[0].end_period = 3
        groups[0].sessions[0].weeks = list(range(1, 10))

        # Teacher A has a hard unavailable slot on T2
        db.add(Constraint(
            semester_id=semester.id,
            name="Teacher A bận",
            constraint_type="UNAVAILABLE",
            hardness="hard",
            weight=1.0,
            lecturer_id=teacher_a.id,
            target={"weekday": 2, "periods": [1, 2, 3]},
            raw_text="Thứ 2 bận họp hội đồng",
            confirmed=True,
        ))
        db.add(NormalizedPreferenceDraft(
            semester_id=semester.id,
            lecturer_id=teacher_a.id,
            context_type="TEACHING",
            source_file="Phieu_Nguyen_Vong.xlsx",
            source_sheet="Sheet A",
            source_row=5,
            source_cell="B5",
            raw_text="Thứ 2 bận họp hội đồng",
            constraint_type="UNAVAILABLE",
            hardness="hard",
            weight=1.0,
            target={"weekday": 2, "periods": [1, 2, 3]},
            confidence="HIGH",
            status="CONFIRMED",
            needs_review=False,
            periods=[1, 2, 3],
            participant_codes=[],
        ))
        db.commit()

        analysis = get_candidate_analysis(db, semester.id, groups[0].id)
        assert len(analysis) == 2  # both lecturers evaluated

        teacher_a_info = next(item for item in analysis if item["lecturer_id"] == teacher_a.id)
        teacher_b_info = next(item for item in analysis if item["lecturer_id"] == teacher_b.id)

        # Teacher A has capability, but hard unavailable on T2
        assert teacher_a_info["has_capability"] is True
        assert teacher_a_info["hard_unavailable"] is True
        assert "Bận cứng" in teacher_a_info["status_label"]
        assert teacher_a_info["preference_source"] is not None
        assert teacher_a_info["preference_source"]["cell"] == "B5"

        # Teacher B has NO capability
        assert teacher_b_info["has_capability"] is False
        assert "Không đủ năng lực" in teacher_b_info["status_label"]


def test_hitl_lock_override_audit_logging():
    """Verify Human-in-the-Loop policy: lock override requires reason and creates audit trail."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 1)
        capability(db, teacher_a, course)
        capability(db, teacher_b, course)
        group = groups[0]

        # First, lock group to teacher_a
        apply_manual_assignment(db, semester.id, group.id, teacher_a.id, True)
        assert group.locked_assignment is True

        # Attempting override without reason must fail
        with pytest.raises(ValueError, match="OVERRIDE_REASON_REQUIRED"):
            override_lock_assignment(db, semester.id, group.id, teacher_b.id, "", user="Test User")

        # Explicit HITL override with reason must succeed
        result = override_lock_assignment(
            db,
            semester.id,
            group.id,
            teacher_b.id,
            "Đặc cách phân công theo yêu cầu chuyên môn của Bộ môn",
            user="Trưởng bộ môn",
            lock=True,
        )
        assert result["success"] is True
        assert result["new_lecturer_id"] == teacher_b.id
        assert group.assigned_lecturer_id == teacher_b.id

        # Verify audit record in ValidationIssue
        audit_records = db.scalars(
            select(ValidationIssue).where(
                ValidationIssue.semester_id == semester.id,
                ValidationIssue.code == "MANUAL_LOCK_OVERRIDE",
            )
        ).all()
        assert len(audit_records) == 1
        audit = audit_records[0]
        assert "Trưởng bộ môn" in audit.message
        assert audit.raw_value == "Đặc cách phân công theo yêu cầu chuyên môn của Bộ môn"


def test_resolution_status_lifecycle():
    """Verify updating and persisting resolution status and notes."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 1)
        group = groups[0]

        res = update_resolution_status(
            db,
            semester.id,
            group.id,
            "UNDER_REVIEW",
            "Đang liên hệ giảng viên thỉnh giảng",
        )
        assert res["resolution_status"] == "UNDER_REVIEW"

        # Verify persisted in raw_values
        assert group.resolution_status == "UNDER_REVIEW"
        assert group.resolution_notes == "Đang liên hệ giảng viên thỉnh giảng"


def test_export_gating_and_privileged_override(tmp_path):
    """Verify Draft export allows unassigned, Final export blocks unless overridden with audit log."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 2)
        capability(db, teacher_a, course)
        capability(db, teacher_b, course)

        # Solve with only 1 class assigned
        db.add(Constraint(
            semester_id=semester.id,
            name="Max 1",
            constraint_type="MAX_CLASSES",
            hardness="hard",
            weight=1.0,
            lecturer_id=teacher_a.id,
            target={"max": 1},
            confirmed=True,
        ))
        db.add(Constraint(
            semester_id=semester.id,
            name="Max 0",
            constraint_type="MAX_CLASSES",
            hardness="hard",
            weight=1.0,
            lecturer_id=teacher_b.id,
            target={"max": 0},
            confirmed=True,
        ))
        db.commit()

        run = solve(db, 2, False, semester.id)
        assert len(diagnose_unassigned_classes(db, semester.id, run.id)) > 0

        # Draft export succeeds
        draft_path = export_latest(db, tmp_path, semester.id, mode="draft")
        assert draft_path.exists()
        assert draft_path.stat().st_size > 0

        # Final export without override is BLOCKED (raises ValueError FINAL_EXPORT_NOT_READY)
        with pytest.raises(ValueError, match="FINAL_EXPORT_NOT_READY"):
            export_latest(db, tmp_path, semester.id, mode="final", allow_unassigned_override=False)

        # Final export with privileged override succeeds and audits
        final_path = export_latest(
            db,
            tmp_path,
            semester.id,
            mode="final",
            allow_unassigned_override=True,
            override_reason="Trưởng bộ môn phê duyệt đặc cách cho kỳ HK1",
        )
        assert final_path.exists()
        assert final_path.stat().st_size > 0

        # Verify audit record
        audit = db.scalar(
            select(ValidationIssue).where(
                ValidationIssue.semester_id == semester.id,
                ValidationIssue.code == "PRIVILEGED_FINAL_EXPORT_OVERRIDE",
            )
        )
        assert audit is not None
        assert "Trưởng bộ môn phê duyệt đặc cách cho kỳ HK1" in audit.raw_value
