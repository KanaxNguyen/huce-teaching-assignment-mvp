import pytest
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Course,
    Department,
    DepartmentProfile,
    Lecturer,
    LecturerCourseCapability,
    Semester,
)
from app.optimization.solver import solve
from app.services.capability_resolution import (
    CapabilityResolutionService,
    HISTORICAL_ASSIGNMENT,
)
from app.services.unassigned_diagnostics import (
    diagnose_unassigned_classes,
    get_candidate_analysis,
)


def _get_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_solver_bridges_equivalent_curriculum_codes():
    """Verify that a lecturer with capability in 440213 ('Tiếng Anh TOEIC 1')

    is bridged to retake code 448805 ('Tiếng Anh TOEIC 1'), allowing LOPNV33 to be assigned.
    """
    db = _get_db()
    dept = Department(name="Bộ môn Ngoại ngữ", code="LANG")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027",
        department_name="Bộ môn Ngoại ngữ",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)

    # Course 1: Regular 440213
    c1 = Course(code="440213", name="Tiếng Anh TOEIC 1")
    # Course 2: Re-take 448805
    c2 = Course(code="448805", name="Tiếng Anh TOEIC 1")
    # Lecturer
    lec = Lecturer(code="GV001", canonical_name="Vũ Thị Ngân", department_id=dept.id, confirmed=True)
    db.add_all([c1, c2, lec])
    db.commit()

    # Capability ONLY for 440213
    cap = LecturerCourseCapability(
        lecturer_id=lec.id,
        course_id=c1.id,
        department_id=dept.id,
        allowed=True,
        confirmed=True,
        source=HISTORICAL_ASSIGNMENT,
    )
    db.add(cap)

    # Class for 448805 (LOPNV33)
    cls = ClassSection(
        semester_id=sem.id,
        course_id=c2.id,
        class_code="LOPNV33",
        credits=3.0,
        source_file="tkb.xls",
        source_sheet="Sheet1",
        source_row=1,
    )
    sess = ClassSession(
        class_section=cls,
        weekday=5,
        start_period=13,
        end_period=15,
        room="105.H1",
        active_weeks=[2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        raw_weeks="2345678901",
        source_row=1,
    )
    db.add_all([cls, sess])
    db.commit()

    # 1. Candidate analysis for LOPNV33 must recognize lecturer as ELIGIBLE
    analysis = get_candidate_analysis(db, sem.id, cls.id)
    assert len(analysis.eligible) == 1
    assert analysis.eligible[0]["lecturer_id"] == lec.id
    row = next(r for r in analysis.analysis_rows if r["lecturer_id"] == lec.id)
    assert row["is_eligible"] is True
    assert "440213" in row["details"]

    # 2. Solver must successfully assign LOPNV33 to the lecturer
    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}
    ass = db.scalar(select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == cls.id))
    assert ass is not None
    assert ass.lecturer_id == lec.id


def test_solver_respects_confirm_merged_flag():
    """Verify that confirm_merged=True forces classes sharing merged_group_id

    to be co-assigned to the same lecturer without timetable collision.
    """
    db = _get_db()
    dept = Department(name="Khoa CNTT", code="IT")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 IT",
        department_name="Khoa CNTT",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    c = Course(code="IT101", name="Lập trình C++")
    lec = Lecturer(code="GV002", canonical_name="Nguyễn Văn A", department_id=dept.id, confirmed=True)
    db.add_all([c, lec])
    db.commit()

    cap = LecturerCourseCapability(
        lecturer_id=lec.id,
        course_id=c.id,
        department_id=dept.id,
        allowed=True,
        confirmed=True,
        source=HISTORICAL_ASSIGNMENT,
    )
    db.add(cap)

    # Two sections at the same time, sharing merged_group_id, but merged_confirmed=False
    sec1 = ClassSection(
        semester_id=sem.id,
        course_id=c.id,
        class_code="68IT1",
        credits=3.0,
        merged_group_id="MERGE_PAIR_01",
        merged_confirmed=False,
        source_file="tkb.xls",
        source_sheet="Sheet1",
        source_row=1,
    )
    sess1 = ClassSession(
        class_section=sec1,
        weekday=2,
        start_period=1,
        end_period=3,
        room="101.A1",
        raw_weeks="123",
        active_weeks=[1, 2, 3],
        source_row=1,
    )
    sec2 = ClassSection(
        semester_id=sem.id,
        course_id=c.id,
        class_code="68IT2",
        credits=3.0,
        merged_group_id="MERGE_PAIR_01",
        merged_confirmed=False,
        source_file="tkb.xls",
        source_sheet="Sheet1",
        source_row=2,
    )
    sess2 = ClassSession(
        class_section=sec2,
        weekday=2,
        start_period=1,
        end_period=3,
        room="101.A1",
        raw_weeks="123",
        active_weeks=[1, 2, 3],
        source_row=2,
    )
    db.add_all([sec1, sess1, sec2, sess2])
    db.commit()

    # If confirm_merged is False: solver cannot assign both to the single lecturer due to overlap
    run_no_merge = solve(db, time_limit_seconds=5, confirm_merged=False, semester_id=sem.id)
    summary_no = run_no_merge.summary or {}
    assert len(summary_no.get("unassigned", [])) == 1

    # If confirm_merged is True: solver treats them as a merged class and assigns both to GV002!
    run_merged = solve(db, time_limit_seconds=5, confirm_merged=True, semester_id=sem.id)
    summary_yes = run_merged.summary or {}
    assert len(summary_yes.get("unassigned", [])) == 0
    ass1 = db.scalar(select(Assignment).where(Assignment.run_id == run_merged.id, Assignment.class_id == sec1.id))
    ass2 = db.scalar(select(Assignment).where(Assignment.run_id == run_merged.id, Assignment.class_id == sec2.id))
    assert ass1 is not None and ass2 is not None
    assert ass1.lecturer_id == ass2.lecturer_id == lec.id


def test_diagnostics_actionable_unblocking():
    """Verify that unassigned diagnostics suggests MERGE_CLASSES, RELAX_PREFERENCES,

    and DEPARTMENT_POOL when a bottleneck occurs.
    """
    db = _get_db()
    dept = Department(name="Bộ môn Ngoại ngữ", code="LANG")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027",
        department_name="Bộ môn Ngoại ngữ",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)

    c = Course(code="448805", name="Tiếng Anh TOEIC 1")
    lec_busy = Lecturer(code="GV001", canonical_name="Phạm Đức Thoan", department_id=dept.id, confirmed=True)
    lec_free = Lecturer(code="GV002", canonical_name="Giảng Viên Rảnh", department_id=dept.id, confirmed=True)
    db.add_all([c, lec_busy, lec_free])
    db.commit()

    # Capable for Thoan
    db.add(LecturerCourseCapability(
        lecturer_id=lec_busy.id,
        course_id=c.id,
        department_id=dept.id,
        allowed=True,
        confirmed=True,
    ))
    # Thoan has hard unavailability on Thursday 13-15
    db.add(Constraint(
        semester_id=sem.id,
        lecturer_id=lec_busy.id,
        name="Bận thứ 5",
        constraint_type="UNAVAILABLE",
        hardness="hard",
        target={"weekday": 5, "periods": [13, 14, 15]},
        confirmed=True,
        active=True,
    ))

    # Two simultaneous classes: LOPNV33 and LOPNV33.1
    cls1 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="LOPNV33", credits=3.0, source_file="s", source_sheet="s", source_row=1)
    cls2 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="LOPNV33.1", credits=3.0, source_file="s", source_sheet="s", source_row=2)
    s1 = ClassSession(class_section=cls1, weekday=5, start_period=13, end_period=15, room="105.H1", raw_weeks="23", active_weeks=[2, 3], source_row=1)
    s2 = ClassSession(class_section=cls2, weekday=5, start_period=13, end_period=15, room="106.H1", raw_weeks="23", active_weeks=[2, 3], source_row=2)
    db.add_all([cls1, cls2, s1, s2])
    db.commit()

    diags = diagnose_unassigned_classes(db, sem.id)
    assert len(diags) == 2
    diag = diags[0]
    action_types = {a["type"] for a in diag["recommended_actions"]}
    assert "MERGE_CLASSES" in action_types
    assert "RELAX_PREFERENCES" in action_types
    assert "DEPARTMENT_POOL" in action_types
    merge_act = next(a for a in diag["recommended_actions"] if a["type"] == "MERGE_CLASSES")
    assert "candidate_class_ids" in merge_act
    assert cls2.id in merge_act["candidate_class_ids"]


def test_solver_never_bypasses_forbidden_capability_with_bridging():
    """Verify that an explicit forbidden capability (allowed=False) on Course 2

    is strictly respected and NEVER overridden by equivalence bridging from Course 1.
    """
    db = _get_db()
    dept = Department(name="D", code="D")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="S",
        department_name="D",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="H",
        is_active=True,
    )
    db.add(sem)

    c1 = Course(code="C1", name="Tiếng Anh TOEIC 1")
    c2 = Course(code="C2", name="Tiếng Anh TOEIC 1")
    lec = Lecturer(code="L1", canonical_name="Lec 1", department_id=dept.id, confirmed=True)
    db.add_all([c1, c2, lec])
    db.commit()

    # Allowed on C1
    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=c1.id, department_id=dept.id, allowed=True, confirmed=True, source="MANUAL"))
    # Explicitly FORBIDDEN on C2
    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=c2.id, department_id=dept.id, allowed=False, confirmed=True, source="MANUAL"))
    db.commit()

    sec = ClassSection(semester_id=sem.id, course_id=c2.id, class_code="SEC2", credits=3.0, source_file="s", source_sheet="s", source_row=1)
    sess = ClassSession(class_section=sec, weekday=2, start_period=1, end_period=3, room="101", raw_weeks="123", active_weeks=[1, 2, 3], source_row=1)
    db.add_all([sec, sess])
    db.commit()

    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    summary = run.summary or {}
    unassigned = summary.get("unassigned", [])
    assert len(unassigned) == 1
    assert unassigned[0]["class_id"] == sec.id

    ass = db.scalar(select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == sec.id))
    assert ass is None


def test_merged_classes_pass_schedule_validation():
    """Verify that when two classes in a merged group are co-assigned to the same teacher,

    validate_schedule passes with valid=True and 0 blocking errors (no false TIMETABLE_CONFLICT).
    """
    from app.services.readiness import validate_schedule

    db = _get_db()
    dept = Department(name="D", code="D")
    db.add(dept)
    db.commit()

    sem = Semester(name="S", department_name="D", department_id=dept.id, start_date=date(2026, 9, 7), end_date=date(2027, 1, 24), head_name="H", is_active=True)
    db.add(sem)

    c = Course(code="C1", name="Course 1")
    lec = Lecturer(code="L1", canonical_name="Lec 1", department_id=dept.id, confirmed=True)
    db.add_all([c, lec])
    db.commit()

    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=c.id, department_id=dept.id, allowed=True, confirmed=True, source="MANUAL"))

    sec1 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="SEC1", credits=3.0, merged_group_id="MG-001", merged_confirmed=True, source_file="s", source_sheet="s", source_row=1)
    sess1 = ClassSession(class_section=sec1, weekday=2, start_period=1, end_period=3, room="101", raw_weeks="123", active_weeks=[1, 2, 3], source_row=1)
    sec2 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="SEC2", credits=3.0, merged_group_id="MG-001", merged_confirmed=True, source_file="s", source_sheet="s", source_row=2)
    sess2 = ClassSession(class_section=sec2, weekday=2, start_period=1, end_period=3, room="101", raw_weeks="123", active_weeks=[1, 2, 3], source_row=2)
    db.add_all([sec1, sess1, sec2, sess2])
    db.commit()

    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}
    val = validate_schedule(db, sem.id, run.id)
    assert val["valid"] is True
    assert len(val.get("blocking_errors", [])) == 0


def test_manual_class_merge_and_unmerge_workflow():
    """Verify that manual merge API merges arbitrary sub-sections and solver co-assigns them."""
    from app.api.routes import merge_classes, unmerge_classes
    from app.schemas.api import MergeClassesRequest, UnmergeClassesRequest

    db = _get_db()
    dept = Department(name="D", code="D")
    db.add(dept)
    db.commit()

    sem = Semester(name="S", department_name="D", department_id=dept.id, start_date=date(2026, 9, 7), end_date=date(2027, 1, 24), head_name="H", is_active=True)
    db.add(sem)

    c = Course(code="448805", name="Tiếng Anh TOEIC 1")
    lec = Lecturer(code="L1", canonical_name="Lec 1", department_id=dept.id, confirmed=True)
    db.add_all([c, lec])
    db.commit()

    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=c.id, department_id=dept.id, allowed=True, confirmed=True, source="MANUAL"))

    # Two classes at same time with DIFFERENT rooms (e.g. LOPNV33 and LOPNV33.1)
    cls1 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="LOPNV33", credits=3.0, source_file="s", source_sheet="s", source_row=1)
    cls2 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="LOPNV33.1", credits=3.0, source_file="s", source_sheet="s", source_row=2)
    s1 = ClassSession(class_section=cls1, weekday=5, start_period=13, end_period=15, room="105.H1", raw_weeks="23", active_weeks=[2, 3], source_row=1)
    s2 = ClassSession(class_section=cls2, weekday=5, start_period=13, end_period=15, room="106.H1", raw_weeks="23", active_weeks=[2, 3], source_row=2)
    db.add_all([cls1, cls2, s1, s2])
    db.commit()

    # 1. Merge them
    res = merge_classes(MergeClassesRequest(class_ids=[cls1.id, cls2.id]), semester_id=sem.id, db=db)
    assert res["confirmed"] is True
    assert cls1.merged_group_id is not None and cls1.merged_group_id == cls2.merged_group_id
    assert cls1.merged_confirmed is True

    # 2. Solve -> single lecturer can take both without conflict!
    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}
    ass1 = db.scalar(select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == cls1.id))
    ass2 = db.scalar(select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == cls2.id))
    assert ass1 is not None and ass2 is not None
    assert ass1.lecturer_id == ass2.lecturer_id == lec.id

    # 3. Unmerge
    unres = unmerge_classes(UnmergeClassesRequest(class_ids=[cls1.id, cls2.id]), semester_id=sem.id, db=db)
    assert unres["unmerged"] == 2
    assert cls1.merged_group_id is None
    assert cls2.merged_group_id is None


def test_diagnostics_safe_when_active_weeks_none():
    """Verify that diagnostics and candidate analysis never crash when active_weeks is None."""
    db = _get_db()
    dept = Department(name="D", code="D")
    db.add(dept)
    db.commit()

    sem = Semester(name="S", department_name="D", department_id=dept.id, start_date=date(2026, 9, 7), end_date=date(2027, 1, 24), head_name="H", is_active=True)
    db.add(sem)

    c = Course(code="C1", name="Course 1")
    lec = Lecturer(code="L1", canonical_name="Lec 1", department_id=dept.id, confirmed=True)
    db.add_all([c, lec])
    db.commit()

    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=c.id, department_id=dept.id, allowed=True, confirmed=True, source="MANUAL"))

    cls1 = ClassSection(semester_id=sem.id, course_id=c.id, class_code="C101", credits=3.0, source_file="s", source_sheet="s", source_row=1)
    s1 = ClassSession(class_section=cls1, weekday=2, start_period=1, end_period=3, room="101", raw_weeks="", active_weeks=None, source_row=1)
    db.add_all([cls1, s1])
    db.commit()

    # Must not raise TypeError: 'NoneType' object is not iterable
    diags = diagnose_unassigned_classes(db, sem.id)
    assert len(diags) == 1
    analysis = get_candidate_analysis(db, sem.id, cls1.id)
    assert len(analysis.analysis_rows) == 1

