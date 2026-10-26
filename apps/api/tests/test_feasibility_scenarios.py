import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.entities import Assignment, ClassSection, Constraint, Course, ValidationIssue
from app.optimization.solver import solve
from app.services.feasibility import precheck
from app.services.resolution_scenarios import apply_scenario, build_scenarios
from test_phase3_solver import capability, setup


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield; Base.metadata.drop_all(engine)


def test_precheck_slot_shortage_is_a_tight_lower_bound():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 3); capability(db, a, c); capability(db, b, c)
        report = precheck(db, s.id)
        shortage = next(item for item in report["items"] if item["code"] == "SLOT_SHORTAGE")
        # The only blocker here is the missing active source, which the API route also enforces.
        assert report["estimated_min_unassigned"] == 1
        assert {i["code"] for i in report["items"] if i["severity"] == "blocking"} == {"NO_ACTIVE_SCHEDULE"}
        assert sorted(shortage["class_ids"]) == sorted(g.id for g in items)
        run = solve(db, 5, False, s.id)
        assert len(run.summary["unassigned"]) == 1


def test_precheck_blocks_models_that_cannot_be_solved():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2); capability(db, a, c)
        db.add(Constraint(semester_id=s.id, name="min", constraint_type="MIN_CLASSES", hardness="hard", weight=1,
                          lecturer_id=a.id, target={"min": 3}, confirmed=True, active=True))
        for item in items:
            item.assigned_lecturer_id = a.id; item.locked_assignment = True
        db.commit()
        codes = {item["code"] for item in precheck(db, s.id)["items"] if item["severity"] == "blocking"}
        assert {"HARD_MIN_UNREACHABLE", "LOCKED_ASSIGNMENT_CONFLICT"} <= codes


def test_swap_scenario_frees_the_only_capable_lecturer():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2)
        other = Course(code="C2", name="Other course"); db.add(other); db.flush()
        items[1].course_id = other.id
        capability(db, a, c); capability(db, b, c); capability(db, a, other)
        items[0].assigned_lecturer_id = a.id; items[0].assignment_source = "IMPORTED"; db.commit()
        result = build_scenarios(db, s.id, items[1].id)
        swap = next(item for item in result["scenarios"] if item["key"] == "swap")
        assert result["recommended"] == "swap" and swap["authority"]["approver"] == "Trưởng bộ môn"
        assert swap["options"][0]["moves"][0]["to_lecturer_id"] == b.id
        apply_scenario(db, s.id, items[1].id, {"scenario": "swap", "lecturer_id": a.id})
        db.expire_all()
        assert (db.get(ClassSection, items[0].id).assigned_lecturer_id, db.get(ClassSection, items[1].id).assigned_lecturer_id) == (b.id, a.id)


def test_rule_bending_scenarios_need_named_approver_and_never_double_book():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 1); capability(db, a, c)
        db.add(Constraint(semester_id=s.id, name="busy", constraint_type="UNAVAILABLE", hardness="hard", weight=1,
                          lecturer_id=a.id, target={"weekday": 2, "periods": [4, 5, 6]}, confirmed=True, active=True)); db.commit()
        consent = next(item for item in build_scenarios(db, s.id, items[0].id)["scenarios"] if item["key"] == "consent")
        assert consent["level"] == 2 and consent["options"][0]["lecturer_id"] == a.id
        with pytest.raises(ValueError):
            apply_scenario(db, s.id, items[0].id, {"scenario": "consent", "lecturer_id": a.id, "reason": "đồng ý"})
        apply_scenario(db, s.id, items[0].id, {"scenario": "consent", "lecturer_id": a.id, "reason": "GV đồng ý qua email", "approver": "TBM X"})
        audit = db.scalar(select(ValidationIssue).where(ValidationIssue.code == "MANUAL_LOCK_OVERRIDE"))
        assert "TBM X" in audit.message and db.get(ClassSection, items[0].id).assignment_source == "MANUAL_OVERRIDE"
        # A lecturer who is not in the chosen scenario cannot be pushed through it.
        with pytest.raises(ValueError):
            apply_scenario(db, s.id, items[0].id, {"scenario": "capability", "lecturer_id": b.id, "reason": "thử", "approver": "X"})


def test_non_mergeable_classes_in_one_merge_group_are_not_forced_unassigned():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2); capability(db, a, c); capability(db, b, c)
        items[1].sessions[0].active_weeks = [2, 3]  # overlaps week 2 but the week masks differ: not mergeable
        for item in items:
            item.merged_group_id = "G1"
        db.commit()
        run = solve(db, 5, True, s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()) == 2


def test_export_post_keeps_reason_out_of_the_url():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 1); capability(db, a, c)
        solve(db, 5, False, s.id)
        semester_id = s.id
    response = TestClient(app).post(f"/api/v1/exports/latest?semester_id={semester_id}",
                                    json={"mode": "draft", "override_reason": "không nằm trong URL"})
    assert response.status_code == 200 and response.content[:2] == b"PK"


def test_precheck_blocks_when_semester_dates_do_not_match_the_file():
    from datetime import date
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2); capability(db, a, c)
        for item in items:
            item.sessions[0].start_date = date(2025, 12, 1); item.sessions[0].end_date = date(2026, 2, 1)
        db.commit()
        finding = next(i for i in precheck(db, s.id)["items"] if i["code"] == "SEMESTER_DATES_MISMATCH")
        assert finding["severity"] == "blocking" and "01/12/2025" in finding["suggestion"] and "Tạo kỳ mới" in finding["suggestion"]


def test_approved_exception_is_honoured_by_precheck_and_solver():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 1); capability(db, a, c)
        apply_scenario(db, s.id, items[0].id, {"scenario": "capability", "lecturer_id": b.id, "reason": "Đã dạy môn này", "approver": "TBM"})
        assert precheck(db, s.id)["items"] == [] or all(i["code"] != "LOCKED_ASSIGNMENT_INVALID" for i in precheck(db, s.id)["items"])
        run = solve(db, 5, False, s.id)
        assert run.status in {"optimal", "feasible"}
        assert db.scalar(select(Assignment).where(Assignment.run_id == run.id)).lecturer_id == b.id
