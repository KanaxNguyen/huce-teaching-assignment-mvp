"""Regressions from the 30-10-2026 synthetic end-to-end run (E2E-01..04)."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.entities import Assignment, Constraint, OptimizationRun, Semester
from app.optimization.solver import solve
from app.services.assignment_state import assignment_state, save_manual_version
from app.services.feasibility import precheck
from app.services.manual_assignment import apply_manual_assignment
from app.services.source_authority import latest_plan_run, run_context
from app.services.unassigned_diagnostics import override_lock_assignment
from test_phase3_solver import setup, capability


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _plan(db, run):
    return {a.class_id: a.lecturer_id for a in db.scalars(select(Assignment).where(Assignment.run_id == run.id))}


def test_e2e01_capability_matrix_upload_is_accepted():
    with SessionLocal() as db:
        semester, *_ = setup(db, 1)
        sid = semester.id
    book = Workbook(); sheet = book.active
    sheet.append(["Mã HP", "Tên HP", "Giảng viên"]); sheet.append(["C", "Course", "[A] A"])
    data = BytesIO(); book.save(data)
    with TestClient(app) as client:
        response = client.post(f"/api/v1/semesters/{sid}/capabilities/import-matrix",
                               files={"file": ("NANG_LUC.xlsx", data.getvalue(),
                                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text


def test_e2e02_override_cannot_double_book_a_locked_lecturer():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2); capability(db, a, c); capability(db, b, c)
        apply_manual_assignment(db, s.id, items[0].id, a.id, True)
        apply_manual_assignment(db, s.id, items[1].id, b.id, True)
        with pytest.raises(ValueError, match="OVERRIDE_NOT_ALLOWED"):
            override_lock_assignment(db, s.id, items[1].id, a.id, "Trưởng bộ môn đồng ý")
        db.rollback()
        assert db.get(type(items[1]), items[1].id).assigned_lecturer_id == b.id
        assert solve(db, 2, False, s.id).status in {"optimal", "feasible"}


def test_e2e03_override_onto_forbidden_lecturer_keeps_the_model_feasible():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 1); capability(db, a, c)
        db.add(Constraint(semester_id=s.id, name="cấm", constraint_type="FORBIDDEN_ASSIGNMENT", hardness="hard",
                          weight=1, lecturer_id=b.id, target={"class_id": items[0].id}, confirmed=True)); db.commit()
        result = override_lock_assignment(db, s.id, items[0].id, b.id, "Đặc cách có duyệt")
        assert "FORBIDDEN_ASSIGNMENT" in result["bypassed_rules"]
        blocking = {i["code"] for i in precheck(db, s.id)["items"] if i["severity"] == "blocking"}
        assert not blocking & {"LOCKED_ASSIGNMENT_INVALID", "LOCKED_ASSIGNMENT_CONFLICT"}
        run = solve(db, 2, False, s.id)
        assert run.status in {"optimal", "feasible"} and _plan(db, run) == {items[0].id: b.id}


def test_e2e04_failed_run_does_not_replace_the_current_plan():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2); capability(db, a, c); capability(db, b, c)
        apply_manual_assignment(db, s.id, items[0].id, b.id, False)
        good = solve(db, 2, False, s.id); plan = _plan(db, good)
        assert len(plan) == 2
        db.add(OptimizationRun(semester_id=s.id, **run_context(db.get(Semester, s.id)), status="blocked",
                               summary={"code": "LOCKED_ASSIGNMENT_CONFLICT"})); db.commit()
        assert latest_plan_run(db, s.id).id == good.id
        assert {cid: lid for cid, (lid, *_) in assignment_state(db, s.id).items()} == plan
        manual = save_manual_version(db, s.id, {}); db.commit()
        assert manual.summary["parent_run_id"] == good.id and _plan(db, manual) == plan
