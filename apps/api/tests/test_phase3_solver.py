from datetime import date

import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.models.entities import Assignment, ClassSection, ClassSession, Constraint, Course, Lecturer, LecturerCourseCapability, Seminar, Semester
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


def test_hard_required_assignment_wins_and_soft_weight_never_makes_rule_hard():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c); capability(db,b,c)
        db.add(Constraint(semester_id=s.id, name="must", constraint_type="REQUIRED_ASSIGNMENT", hardness="hard", weight=0, lecturer_id=b.id, target={"class_id": items[0].id}, confirmed=True))
        db.add(Constraint(semester_id=s.id, name="soft avoid", constraint_type="FORBIDDEN_ASSIGNMENT", hardness="soft", weight=1, lecturer_id=a.id, target={"class_id": items[0].id}, confirmed=True))
        db.commit()
        run = solve(db, 2, False, s.id)
        assert db.scalar(select(Assignment).where(Assignment.run_id == run.id)).lecturer_id == b.id


def test_shared_hard_seminar_blocks_participant_once_at_selected_slot():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c)
        db.add(Seminar(semester_id=s.id, name="Seminar", chair_name="", members=[a.id], alternatives=[{"weekday": 2, "periods": [4, 5, 6]}], hardness="hard", weight=0.8))
        db.commit()
        run = solve(db, 2, False, s.id)
        assert run.summary["unassigned"]
        assert run.summary["seminars"][0]["scheduled"] is True


def test_max_consecutive_blocks_hard_binds_but_soft_remains_violable():
    with SessionLocal() as db:
        s, c, a, b, items = setup(db, 2)
        capability(db, a, c)
        # Two adjacent teaching blocks on the same day, with no timetable
        # overlap.  A HARD cap of one block must leave one group unassigned.
        items[1].sessions[0].start_period = 7
        items[1].sessions[0].end_period = 9
        db.add(Constraint(
            semester_id=s.id, name="one block", constraint_type="MAX_CONSECUTIVE_BLOCKS",
            hardness="hard", weight=1, lecturer_id=a.id, target={"max": 1}, confirmed=True,
        ))
        db.commit()
        hard_run = solve(db, 2, False, s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id == hard_run.id)).all()) == 1

        constraint = db.scalar(select(Constraint).where(Constraint.semester_id == s.id))
        constraint.hardness = "soft"
        db.commit()
        soft_run = solve(db, 2, False, s.id)
        assert len(db.scalars(select(Assignment).where(Assignment.run_id == soft_run.id)).all()) == 2


def test_course_scoped_forbidden_assignment_applies_to_every_teaching_group():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db, 2); capability(db,a,c); capability(db,b,c)
        db.add(Constraint(semester_id=s.id, name="no course", constraint_type="FORBIDDEN_ASSIGNMENT", hardness="hard", weight=0, lecturer_id=a.id, target={"course_id": c.id}, confirmed=True))
        db.commit()
        run = solve(db, 2, False, s.id)
        assert {item.lecturer_id for item in db.scalars(select(Assignment).where(Assignment.run_id == run.id))} == {b.id}


def test_calendar_constraint_date_scope_does_not_block_outside_its_range():
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c)
        items[0].sessions[0].start_date = date(2026, 2, 1)
        items[0].sessions[0].end_date = date(2026, 2, 28)
        db.add(Constraint(semester_id=s.id, name="January only", constraint_type="unavailable", hardness="hard", weight=0, lecturer_id=a.id, target={"weekday": 2, "periods": [4, 5, 6], "start_date": "2026-01-01", "end_date": "2026-01-31"}, confirmed=True))
        db.commit()
        run = solve(db, 2, False, s.id)
        assert db.scalar(select(Assignment).where(Assignment.run_id == run.id)).lecturer_id == a.id
