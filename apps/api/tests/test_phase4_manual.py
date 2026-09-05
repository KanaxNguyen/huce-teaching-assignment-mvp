from datetime import date
from sqlalchemy import select
from fastapi import HTTPException
import pytest
from app.db.session import Base, SessionLocal, engine
from app.models.entities import Assignment, ClassSection, ClassSession, Constraint, Semester
from app.optimization.solver import solve
from app.services.manual_assignment import apply_manual_assignment, check_assignment_change
from app.api.routes import class_candidates, get_problems, manual_assignment, lock_assignment, unlock_assignment, check_assignment
from test_phase3_solver import setup, capability

@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield; Base.metadata.drop_all(engine)

def test_manual_assign_lock_unlock_and_resolve():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,2); capability(db,a,c); capability(db,b,c)
        assert apply_manual_assignment(db,s.id,items[0].id,a.id,True)["locked"]
        run=solve(db,2,False,s.id)
        assert db.scalar(select(Assignment).where(Assignment.run_id==run.id,Assignment.class_id==items[0].id)).lecturer_id==a.id
        items[0].locked_assignment=False; items[0].assignment_source=None; db.commit()
        assert solve(db,2,False,s.id).status in {"optimal","feasible"}


def test_unlocked_manual_assignment_is_reconsidered_by_solver():
    """Unlock is semantic, not merely a presentation-state change."""
    with SessionLocal() as db:
        semester, course, teacher_a, teacher_b, groups = setup(db, 1)
        capability(db, teacher_a, course); capability(db, teacher_b, course)
        group = groups[0]
        assert apply_manual_assignment(db, semester.id, group.id, teacher_a.id, True)["locked"]
        assert unlock_assignment(group.id, semester.id, db)["locked"] is False
        db.add(Constraint(
            semester_id=semester.id, name="must use B", constraint_type="REQUIRED_ASSIGNMENT",
            hardness="hard", weight=1, lecturer_id=teacher_b.id,
            target={"class_id": group.id}, confirmed=True,
        )); db.commit()
        run = solve(db, 2, False, semester.id)
        assignment = db.scalar(select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == group.id))
        assert run.status in {"optimal", "feasible"}
        assert assignment.lecturer_id == teacher_b.id

def test_manual_validation_and_constraint_limits():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,2); capability(db,a,c)
        assert "COURSE_CAPABILITY_MISSING" in check_assignment_change(db,s.id,items[0].id,b.id)["blocking_reasons"]
        db.add(Constraint(semester_id=s.id,name="max",constraint_type="MAX_CLASSES",hardness="hard",weight=1,lecturer_id=a.id,target={"max":1},confirmed=True)); db.commit()
        run=solve(db,2,False,s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id==run.id)).all())==1

def test_session_day_days_required_forbidden_and_malformed_constraints():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,3); capability(db,a,c); capability(db,b,c)
        items[1].sessions[0].weekday=3; items[2].sessions[0].weekday=4; db.commit()
        db.add_all([
            Constraint(semester_id=s.id,name="sessions",constraint_type="MAX_SESSIONS_PER_DAY",hardness="hard",weight=1,lecturer_id=a.id,target={"max":1},confirmed=True),
            Constraint(semester_id=s.id,name="days",constraint_type="MAX_DAYS_PER_WEEK",hardness="hard",weight=1,lecturer_id=a.id,target={"max":2},confirmed=True),
            Constraint(semester_id=s.id,name="required",constraint_type="REQUIRED_ASSIGNMENT",hardness="hard",weight=1,lecturer_id=b.id,target={"class_id":items[0].id},confirmed=True),
            Constraint(semester_id=s.id,name="forbidden",constraint_type="FORBIDDEN_ASSIGNMENT",hardness="hard",weight=1,lecturer_id=a.id,target={"class_id":items[0].id},confirmed=True),
            Constraint(semester_id=s.id,name="bad",constraint_type="REQUIRED_ASSIGNMENT",hardness="hard",weight=1,lecturer_id=a.id,target={},confirmed=True),
        ]); db.commit(); run=solve(db,2,False,s.id)
        assignment=db.scalar(select(Assignment).where(Assignment.run_id==run.id,Assignment.class_id==items[0].id))
        assert assignment.lecturer_id==b.id and run.summary["invalid_constraints"]

def test_candidate_problem_log_and_semester_isolation():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,1); capability(db,a,c)
        candidates=class_candidates(items[0].id,s.id,db)
        assert {x["lecturer_id"]:x["status"] for x in candidates}[a.id]=="ELIGIBLE"
        assert {x["lecturer_id"]:x["status"] for x in candidates}[b.id]=="COURSE_CAPABILITY_MISSING"
        db.add(Constraint(semester_id=s.id,name="unknown",constraint_type="mystery",hardness="soft",weight=1,target={},confirmed=True)); db.commit(); solve(db,2,False,s.id)
        assert any(x["code"]=="UNSUPPORTED_CONSTRAINT_TYPE" for x in get_problems(s.id,db))


def test_problem_log_explains_locked_conflict_in_human_language():
    with SessionLocal() as db:
        semester, course, teacher_a, _teacher_b, groups = setup(db, 2)
        capability(db, teacher_a, course)
        for group in groups:
            group.assigned_lecturer_id = teacher_a.id
            group.locked_assignment = True
        db.commit(); solve(db, 2, False, semester.id)
        problem = next(item for item in get_problems(semester.id, db) if item["code"] == "LOCKED_ASSIGNMENT_CONFLICT")
        assert problem["severity"] == "critical"
        assert "phân công đã khóa" in problem["message"]
        assert problem["reasons"] and groups[0].class_code in problem["reasons"][0]["reason"]

def test_atomic_assign_and_lock_rolls_back_when_commit_fails(monkeypatch):
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,1); capability(db,a,c); capability(db,b,c)
        items[0].assigned_lecturer_id=a.id; items[0].assignment_source="MANUAL"; items[0].locked_assignment=False; db.commit(); class_id=items[0].id; sid=s.id; aid=a.id
        monkeypatch.setattr(db,"commit",lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")))
        with pytest.raises(RuntimeError): apply_manual_assignment(db,sid,class_id,b.id,True)
    with SessionLocal() as verify:
        group=verify.get(ClassSection,class_id)
        assert (group.assigned_lecturer_id,group.assignment_source,group.locked_assignment)==(aid,"MANUAL",False)

def test_manual_operations_are_scoped_to_semester():
    with SessionLocal() as db:
        a,c,teacher,other,items=setup(db,1); capability(db,teacher,c)
        b=Semester(name="B",department_name="D",start_date=date(2026,1,1),end_date=date(2026,6,1),head_name="H"); db.add(b); db.flush()
        foreign=ClassSection(semester_id=b.id,course_id=c.id,class_code="B",source_file="f",source_sheet="s",source_row=2); db.add(foreign); db.flush(); db.add(ClassSession(class_id=foreign.id,weekday=3,start_period=1,end_period=3,room="P",start_date=None,end_date=None,raw_weeks="1",active_weeks=[1],source_row=2)); db.commit()
        for call in (
            lambda: manual_assignment(foreign.id,{"lecturer_id":teacher.id,"lock":True},a.id,db),
            lambda: lock_assignment(foreign.id,a.id,db),
            lambda: unlock_assignment(foreign.id,a.id,db),
            lambda: class_candidates(foreign.id,a.id,db),
            lambda: check_assignment(foreign.id,{"lecturer_id":teacher.id},a.id,db),
        ):
            with pytest.raises(HTTPException): call()
        verify_state = (db.get(ClassSection,foreign.id).assigned_lecturer_id, db.get(ClassSection,foreign.id).locked_assignment)
        assert verify_state == (None,False)
        assert manual_assignment(items[0].id,{"lecturer_id":teacher.id,"lock":False},a.id,db)["valid"]
