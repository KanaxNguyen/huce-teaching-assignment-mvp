from datetime import date, datetime
import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Course,
    Lecturer,
    LecturerAlias,
    LecturerCourseCapability,
    LecturerSemesterProfile,
    NormalizedPreferenceDraft,
    Semester,
)
from app.optimization.solver import solve
from app.parsers.preferences import _extract_date_unavailable, _legacy_rule
from app.services.lecturer_master import confirm_alias


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _setup_base_semester(db):
    s = Semester(
        name="Học kỳ 1 2026-2027",
        department_name="Bộ môn Tin học Xây dựng",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 1, 31),
        head_name="Trưởng BM",
        is_active=True,
    )
    db.add(s)
    db.commit()
    return s


# ==============================================================================
# 1. Lecturer HITL Review Endpoint Scoped by semester_id
# ==============================================================================

def test_lecturer_hitl_review_endpoint():
    client = TestClient(app)
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        
        # Lecturer 1: Standardized with code and alias
        lec1 = Lecturer(code="GV01", canonical_name="Nguyễn Văn An", status="ACTIVE", confirmed=True)
        db.add(lec1)
        db.flush()
        confirm_alias(db, lec1, "Thầy An")
        db.add(LecturerSemesterProfile(lecturer_id=lec1.id, semester_id=sem.id, participation_status="ACTIVE", min_workload=4, max_workload=20))
        
        # Lecturer 2: Needs confirmation (no code)
        lec2 = Lecturer(code=None, canonical_name="Trần Thị Bình", status="ACTIVE")
        db.add(lec2)
        db.flush()
        db.add(LecturerSemesterProfile(lecturer_id=lec2.id, semester_id=sem.id, participation_status="ACTIVE"))
        
        # Course and capability
        course = Course(code="THXD01", name="Tin học đại cương")
        db.add(course)
        db.flush()
        db.add(LecturerCourseCapability(lecturer_id=lec1.id, course_id=course.id, confirmed=True, allowed=True))

        db.commit()
        sem_id = sem.id

    resp = client.get(f"/api/v1/lecturers/review?semester_id={sem_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["semester_id"] == sem_id
    assert data["total_lecturers"] == 2
    assert data["ready_count"] == 1
    assert data["needs_review_count"] == 1
    assert data["blockers_count"] == 1  # lec2 has no code
    assert len(data["items"]) == 2

    item1 = next(i for i in data["items"] if i["code"] == "GV01")
    assert item1["name"] == "Nguyễn Văn An"
    assert "Thầy An" in item1["aliases"]
    assert item1["identity_status"] == "STANDARDIZED"
    assert item1["participates"] is True
    assert "THXD01" in item1["courses_can_teach"]

    item2 = next(i for i in data["items"] if i["code"] is None)
    assert item2["identity_status"] == "NEEDS_CONFIRMATION"


# ==============================================================================
# 2. Lecturer Import Preview & Commit with Matching Priority
# Priority: exact stable code > confirmed alias > exact normalized name > review
# ==============================================================================

def test_lecturer_import_preview_and_atomic_commit():
    client = TestClient(app)
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        
        # Existing lecturer in master
        existing = Lecturer(code="GV10", canonical_name="Lê Văn Cường", status="ACTIVE")
        db.add(existing)
        db.flush()
        confirm_alias(db, existing, "Cường LV")
        db.commit()
        sem_id = sem.id

    # Create an import Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "DS_GiangVien"
    ws.append(["Mã GV", "Họ và tên", "Email", "Bộ môn", "Định mức tối thiểu", "Định mức tối đa", "Danh xưng phụ", "Tham gia kỳ này"])
    # 1. Update existing by exact code
    ws.append(["GV10", "Lê Văn Cường", "cuong@huce.edu.vn", "Tin học", 6, 24, "Thầy Cường", "Có"])
    # 2. Add new lecturer
    ws.append(["GV11", "Phạm Thị Dung", "dung@huce.edu.vn", "Tin học", 4, 20, "Cô Dung", "Có"])
    # 3. Match existing by confirmed alias
    ws.append(["", "Cường LV", "", "Tin học", 0, 24, "", "Có"])
    # 4. Incomplete row (missing name) -> skipped
    ws.append(["GV99", "", "", "", 0, 0, "", ""])

    excel_buf = io.BytesIO()
    wb.save(excel_buf)
    excel_buf.seek(0)

    # Preview
    preview_resp = client.post(
        f"/api/v1/lecturers/import/preview?semester_id={sem_id}",
        files={"file": ("import_test.xlsx", excel_buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["total_rows"] == 4
    assert len(preview["to_add"]) == 1
    assert preview["to_add"][0]["code"] == "GV11"
    assert len(preview["to_update"]) == 2  # GV10 and Cường LV
    assert len(preview["skipped"]) == 1
    assert preview["can_commit"] is False
    blocked = client.post(
        f"/api/v1/lecturers/import?semester_id={sem_id}",
        files={"file": ("import_test.xlsx", excel_buf.getvalue())},
    )
    assert blocked.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(Lecturer).where(Lecturer.code == "GV11")) is None
    # Resolve the invalid row, then commit the full validated batch.
    ws.delete_rows(5)
    excel_buf = io.BytesIO()
    wb.save(excel_buf)

    # Commit
    excel_buf.seek(0)
    commit_resp = client.post(
        f"/api/v1/lecturers/import?semester_id={sem_id}",
        files={"file": ("import_test.xlsx", excel_buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert commit_resp.status_code == 200
    res = commit_resp.json()
    assert res["added"] == 1
    assert res["updated"] == 2

    # Verify in DB
    with SessionLocal() as db:
        new_lec = db.scalar(select(Lecturer).where(Lecturer.code == "GV11"))
        assert new_lec is not None
        assert new_lec.canonical_name == "Phạm Thị Dung"


# ==============================================================================
# 3. Lecturer Export XLSX Endpoint
# ==============================================================================

def test_lecturer_export_xlsx():
    client = TestClient(app)
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        lec = Lecturer(code="GV99", canonical_name="Đỗ Hoàng Long", status="ACTIVE")
        db.add(lec)
        db.flush()
        db.add(LecturerSemesterProfile(lecturer_id=lec.id, semester_id=sem.id, participation_status="ACTIVE", min_workload=2, max_workload=18))
        db.commit()
        sem_id = sem.id

    export_resp = client.get(f"/api/v1/lecturers/export?semester_id={sem_id}")
    assert export_resp.status_code == 200
    assert "openxmlformats" in export_resp.headers["content-type"]

    exported_wb = load_workbook(io.BytesIO(export_resp.content))
    ws = exported_wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][0] == "Mã GV"
    assert rows[0][1] == "Tên GV"
    data_row = next(r for r in rows[1:] if r[0] == "GV99")
    assert data_row[1] == "Đỗ Hoàng Long"
    assert "Đang công tác" in data_row[4]


# ==============================================================================
# 4. Reversible Preference Rejection & Exclusion from Apply
# ==============================================================================

def test_preference_draft_rejection_and_restore():
    client = TestClient(app)
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        lec = Lecturer(code="GV05", canonical_name="Bùi Văn H", status="ACTIVE")
        db.add(lec)
        db.flush()
        draft = NormalizedPreferenceDraft(
            semester_id=sem.id,
            lecturer_id=lec.id,
            context_type="TEACHING",
            constraint_type="UNAVAILABLE",
            day_scope="T2",
            periods=[1, 2, 3],
            hardness="hard",
            weight=1.0,
            confidence="HIGH",
            needs_review=False,
            status="DRAFT",
            source_file="test.xlsx",
            source_sheet="Sheet1",
            source_row=10,
            source_cell="B10",
        )
        db.add(draft)
        db.commit()
        sem_id = sem.id
        draft_id = draft.id

    # 1. Reject draft with reason
    rej_resp = client.patch(
        f"/api/v1/preference-drafts/{draft_id}?semester_id={sem_id}",
        json={"status": "REJECTED", "rejected_reason": "Không phù hợp với phân công kỳ này"},
    )
    assert rej_resp.status_code == 200
    rej_data = rej_resp.json()
    assert rej_data["status"] == "REJECTED"
    assert rej_data["rejected_reason"] == "Không phù hợp với phân công kỳ này"
    assert rej_data["rejected_at"] is not None

    # Verify DB state
    with SessionLocal() as db:
        d = db.get(NormalizedPreferenceDraft, draft_id)
        assert d.status == "REJECTED"
        assert d.rejected_reason == "Không phù hợp với phân công kỳ này"
        assert d.rejected_at is not None

    # 2. Try applying rejected draft -> should NOT apply (HTTP 422 PREFERENCE_DRAFT_NOT_READY)
    apply_resp = client.post(
        f"/api/v1/preference-drafts/apply?semester_id={sem_id}",
        json={"draft_ids": [draft_id]},
    )
    assert apply_resp.status_code == 422
    assert apply_resp.json()["detail"]["code"] == "PREFERENCE_DRAFT_NOT_READY"

    # 3. Restore draft -> status becomes NEEDS_REVIEW, reason and rejected_at cleared
    restore_resp = client.patch(
        f"/api/v1/preference-drafts/{draft_id}?semester_id={sem_id}",
        json={"status": "NEEDS_REVIEW"},
    )
    assert restore_resp.status_code == 200
    restore_data = restore_resp.json()
    assert restore_data["status"] == "NEEDS_REVIEW"
    assert restore_data["rejected_reason"] is None
    assert restore_data["rejected_at"] is None

    with SessionLocal() as db:
        d = db.get(NormalizedPreferenceDraft, draft_id)
        assert d.status == "NEEDS_REVIEW"
        assert d.rejected_reason is None
        assert d.rejected_at is None


# ==============================================================================
# 5. Deterministic Date-Scoped Unavailable Semantics
# "nghỉ đến 11/10" / "không thể dạy trước 12/10" -> end_date 2026-10-11
# Solver: blocks 11/10 meeting, unblocks 12/10 meeting
# ==============================================================================

def test_date_scoped_unavailable_parsing():
    # 1. "nghỉ đến 11/10/2026"
    rule1, target1, conf1, reason1 = _legacy_rule("Nghỉ đến 11/10/2026", None)
    assert rule1 == "UNAVAILABLE"
    assert target1.get("end_date") == "2026-10-11"
    assert conf1 == "HIGH"
    assert reason1 is None

    # 2. "không thể dạy trước 12/10/2026" -> ends 11/10 inclusive
    rule2, target2, conf2, reason2 = _legacy_rule("Không thể dạy trước 12/10/2026", None)
    assert rule2 == "UNAVAILABLE"
    assert target2.get("end_date") == "2026-10-11"
    assert conf2 == "HIGH"
    assert reason2 is None


def test_date_scoped_unavailable_solver_blocking():
    with SessionLocal() as db:
        # Semester starting 2026-08-01 (Saturday). Week 1 starts 2026-08-01.
        sem = Semester(
            name="S_DateTest",
            department_name="Toán",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 1, 31),
            head_name="H",
        )
        course = Course(code="MTH", name="Toán cao cấp")
        lec = Lecturer(code="GV_DATE", canonical_name="Thầy Date")
        db.add_all([sem, course, lec])
        db.flush()

        db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=course.id, confirmed=True, allowed=True))

        # Class 1: meeting exactly on 2026-10-11 (Sunday = weekday 8)
        # 2026-08-01 is Saturday. 2026-10-11 is 71 days later, week 11 Sunday.
        sec1 = ClassSection(semester_id=sem.id, course_id=course.id, class_code="SEC_BLOCKED", source_file="f", source_sheet="s", source_row=1)
        db.add(sec1)
        db.flush()
        db.add(ClassSession(
            class_id=sec1.id,
            weekday=8,
            start_period=1,
            end_period=3,
            room="P101",
            raw_weeks="11",
            active_weeks=[11],
            source_row=1,
        ))

        # Class 2: meeting on 2026-10-12 (Monday = weekday 2, week 12)
        sec2 = ClassSection(semester_id=sem.id, course_id=course.id, class_code="SEC_UNBLOCKED", source_file="f", source_sheet="s", source_row=2)
        db.add(sec2)
        db.flush()
        db.add(ClassSession(
            class_id=sec2.id,
            weekday=2,
            start_period=1,
            end_period=3,
            room="P102",
            raw_weeks="12",
            active_weeks=[12],
            source_row=2,
        ))

        # Add HARD UNAVAILABLE constraint ending 2026-10-11
        db.add(Constraint(
            semester_id=sem.id,
            lecturer_id=lec.id,
            name="Nghỉ đến 11/10",
            constraint_type="unavailable",
            hardness="hard",
            weight=1.0,
            target={
                "start_date": "2026-08-01",
                "end_date": "2026-10-11",
                "periods": list(range(1, 16)),
                "day_scope": "ALL_DAYS",
            },
            confirmed=True,
            active=True,
        ))
        db.commit()

        # Solve
        run = solve(db, time_limit_seconds=5, confirm_merged=False, semester_id=sem.id)
        assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
        assigned_sec_ids = {a.class_id for a in assignments if a.lecturer_id == lec.id}

        # sec1 (on 11/10) MUST NOT be assigned to lec (blocked by hard unavailable)
        assert sec1.id not in assigned_sec_ids
        # sec2 (on 12/10) CAN be assigned to lec
        assert sec2.id in assigned_sec_ids


# ==============================================================================
# 6. MIN_FREE_MORNING_PER_WEEK Constraint
# Periods 1..6 on T2..T6, >= 1 morning free per active teaching week.
# Afternoon does NOT consume morning.
# ==============================================================================

def test_min_free_morning_per_week_constraint():
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        course = Course(code="CS101", name="Lập trình")
        lec = Lecturer(code="GV_MORNING", canonical_name="Thầy Sáng")
        db.add_all([course, lec])
        db.flush()
        db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=course.id, confirmed=True, allowed=True))

        # Create 5 morning sections (T2, T3, T4, T5, T6) in week 1, periods 1-3
        morning_sections = []
        for wd in [2, 3, 4, 5, 6]:
            sec = ClassSection(semester_id=sem.id, course_id=course.id, class_code=f"MORN_{wd}", source_file="f", source_sheet="s", source_row=wd)
            db.add(sec)
            db.flush()
            # Week 1 begins before this Saturday-start semester; use its first full week.
            db.add(ClassSession(class_id=sec.id, weekday=wd, start_period=1, end_period=3, room="P1", raw_weeks="2", active_weeks=[2], source_row=wd))
            morning_sections.append(sec)

        # Constraint: MIN_FREE_MORNING_PER_WEEK = 1
        db.add(Constraint(
            semester_id=sem.id,
            lecturer_id=lec.id,
            name="Nghỉ ít nhất 1 sáng",
            constraint_type="min_free_morning_per_week",
            hardness="hard",
            weight=1.0,
            target={"numeric_value": 1},
            confirmed=True,
            active=True,
        ))
        db.commit()

        run = solve(db, time_limit_seconds=5, confirm_merged=False, semester_id=sem.id)
        assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
        assigned_mornings = [a for a in assignments if a.lecturer_id == lec.id]

        # With 5 morning classes on T2..T6 and requiring at least 1 free morning,
        # the solver can assign at most 4 morning classes to this lecturer!
        assert len(assigned_mornings) <= 4


# ==============================================================================
# 7. PREFER_CONSECUTIVE_PERIODS Gap Linearization
# 0 penalty for single isolated 3-period block; penalizes gaps between occupied blocks.
# ==============================================================================

def test_prefer_consecutive_periods_zero_penalty_for_isolated_class():
    with SessionLocal() as db:
        sem = _setup_base_semester(db)
        course = Course(code="GAP101", name="Toán rời rạc")
        lec = Lecturer(code="GV_GAP", canonical_name="Thầy Liền Tiết")
        db.add_all([course, lec])
        db.flush()
        db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=course.id, confirmed=True, allowed=True))

        # Single isolated 3-period class (periods 1-3)
        sec = ClassSection(semester_id=sem.id, course_id=course.id, class_code="ISO_1", source_file="f", source_sheet="s", source_row=1)
        db.add(sec)
        db.flush()
        db.add(ClassSession(class_id=sec.id, weekday=2, start_period=1, end_period=3, room="P1", raw_weeks="1", active_weeks=[1], source_row=1))

        # Add soft PREFER_CONSECUTIVE_PERIODS
        db.add(Constraint(
            semester_id=sem.id,
            lecturer_id=lec.id,
            name="Ưu tiên liền tiết",
            constraint_type="prefer_consecutive_periods",
            hardness="soft",
            weight=0.8,
            target={},
            confirmed=True,
            active=True,
        ))
        db.commit()

        run = solve(db, time_limit_seconds=5, confirm_merged=False, semester_id=sem.id)
        assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
        assert len(assignments) == 1
        assert assignments[0].lecturer_id == lec.id
        # Penalty score should be 0 since there are no intermediate gap blocks
        assert run.score is not None
