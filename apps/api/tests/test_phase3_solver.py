from datetime import date

import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.models.entities import Assignment, ClassSection, ClassSession, Constraint, Course, Lecturer, LecturerCourseCapability, Semester
from app.optimization.solver import eligible_teachers, solve


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield; Base.metadata.drop_all(engine)


def setup(db, groups=1):
    semester = Semester(name="S", department_name="D", start_date=date(2026,1,1), end_date=date(2026,6,1), head_name="H")
    course = Course(code="C", name="Course"); a = Lecturer(code="A", canonical_name="A"); b = Lecturer(code="B", canonical_name="B")
    db.add_all([semester, course, a, b]); db.flush()
    sections=[]
    for n in range(groups):
        item=ClassSection(semester_id=semester.id, course_id=course.id, class_code=f"L{n}", source_file="f", source_sheet="s", source_row=n)
        db.add(item); db.flush(); db.add(ClassSession(class_id=item.id, weekday=2, start_period=4, end_period=6, room="P", start_date=None, end_date=None, raw_weeks="12", active_weeks=[1,2], source_row=n)); sections.append(item)
    db.commit(); return semester, course, a, b, sections


def capability(db, teacher, course, confirmed=True, allowed=True):
    db.add(LecturerCourseCapability(lecturer_id=teacher.id, course_id=course.id, confirmed=confirmed, allowed=allowed)); db.commit()


def test_capability_filters_and_partial_unassigned():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db, 2); capability(db,a,c)
        caps={c.id: db.scalars(select(LecturerCourseCapability)).all()}
        assert eligible_teachers(items[0], caps) == {a.id}
        run=solve(db,2,False,s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id==run.id)).all()) == 1
        assert run.summary["unassigned"][0]["reasons"][0]["reason"] in {"TIMETABLE_CONFLICT","NO_ELIGIBLE_LECTURER"}


def test_soft_preference_never_beats_completeness():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c)
        db.add(Constraint(semester_id=s.id,name="prefer",constraint_type="prefer_period",hardness="soft",weight=1,lecturer_id=a.id,target={"weekday":3,"periods":[1]} ,confirmed=True)); db.commit()
        run=solve(db,2,False,s.id)
        assert db.scalar(select(Assignment).where(Assignment.run_id==run.id)).lecturer_id == a.id


def test_locked_conflict_and_unconfirmed_merge():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,2); capability(db,a,c)
        for item in items: item.locked_assignment=True; item.assigned_lecturer_id=a.id
        db.commit(); assert solve(db,2,False,s.id).summary["code"] == "LOCKED_ASSIGNMENT_CONFLICT"
        for item in items: item.locked_assignment=False; item.merged_group_id="M"; item.merged_confirmed=False
        db.commit(); run=solve(db,2,False,s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id==run.id)).all()) == 1


def test_confirmed_merge_and_different_weeks():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,2); capability(db,a,c)
        for item in items: item.merged_group_id="M"; item.merged_confirmed=True
        db.commit(); run=solve(db,2,False,s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id==run.id)).all()) == 2
        for item in items: item.merged_confirmed=False; item.merged_group_id=None
        items[1].sessions[0].active_weeks=[3]; db.commit(); run=solve(db,2,False,s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id==run.id)).all()) == 2


def test_multi_meeting_hard_unavailable_and_week_aware_conflict():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db,2); capability(db,a,c)
        db.add(ClassSession(class_id=items[0].id,weekday=4,start_period=4,end_period=6,room="P",start_date=None,end_date=None,raw_weeks="12",active_weeks=[1,2],source_row=5))
        db.add(Constraint(semester_id=s.id,name="no",constraint_type="unavailable",hardness="hard",weight=1,lecturer_id=a.id,target={"weekday":4,"periods":[4,5,6]},confirmed=True)); db.commit()
        run=solve(db,2,False,s.id)
        assert len(run.summary["unassigned"]) == 1


def test_unsupported_constraint_and_failed_run_preserves_previous_snapshot():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c)
        valid=solve(db,2,False,s.id); before=[x.id for x in db.scalars(select(Assignment).where(Assignment.run_id==valid.id))]
        items[0].locked_assignment=True; items[0].assigned_lecturer_id=b.id; db.commit()
        blocked=solve(db,2,False,s.id)
        assert blocked.status == "blocked" and before == [x.id for x in db.scalars(select(Assignment).where(Assignment.run_id==valid.id))]
        db.add(Constraint(semester_id=s.id,name="x",constraint_type="mystery",hardness="soft",weight=1,target={},confirmed=True)); db.commit()
        assert "mystery" in solve(db,2,False,s.id).summary["unsupported_constraints"]
