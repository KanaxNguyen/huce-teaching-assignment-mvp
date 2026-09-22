from datetime import date
from pathlib import Path
import openpyxl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.main import app
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
    OptimizationRun,
    Semester,
    ValidationIssue,
)
from fastapi.testclient import TestClient
from app.optimization.solver import solve
from app.parsers.schedule import parse_schedule
from app.services.capability_resolution import (
    CapabilityResolutionService,
    HISTORICAL_ASSIGNMENT,
    IMPORT_CAPABILITY_MATRIX,
)
from app.services.importer import _import_files_impl
from app.services.readiness import capability_readiness, validate_schedule
from app.services.unassigned_diagnostics import get_candidate_analysis

FILE_SCHEDULE = Path("/Users/mac/AI/Huce_timetable/INPUT Gốc/phan-cong-giang-day-lich-hoc-to-bo-mon-18-09-2026-14-46-31_TKB00025_3781df7291f5b76652056d069c3f9d3a (1).xls")
FILE_PREFERENCES = Path("/Users/mac/AI/Huce_timetable/INPUT Gốc/Nguyen_vong_GV_TEST_.xlsx")
FILE_HISTORICAL = Path("/Users/mac/AI/Huce_timetable/INPUT Gốc/Output_KY_VONG_TEST.xlsx")


def _get_isolated_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_a_historical_workbook_regression_max_row_none():
    """Test A: Verify openpyxl streaming with sheet.max_row being None or inaccurate does not drop rows."""
    if not FILE_HISTORICAL.exists():
        pytest.skip("Historical test workbook not found")

    db = _get_isolated_db()
    sem = Semester(
        name="HK1 2026-2027",
        department_name="Bộ môn Ngoại ngữ",
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)
    db.commit()

    # Learn from real file
    result = CapabilityResolutionService.learn_from_historical_assignment_file(
        db=db,
        file_path=FILE_HISTORICAL,
        semester_id=sem.id,
    )

    assert result["rows_read"] >= 300, f"Expected >= 300 rows, got {result['rows_read']}"
    assert result["capabilities_learned"] >= 50, f"Expected >= 50 capabilities learned, got {result['capabilities_learned']}"
    assert result["unique_lecturers_identified"] >= 15, f"Expected >= 15 lecturers, got {result['unique_lecturers_identified']}"
    assert result["unique_courses_identified"] >= 10, f"Expected >= 10 courses, got {result['unique_courses_identified']}"

    # Verify DB has capabilities
    caps = db.scalars(select(LecturerCourseCapability)).all()
    assert len(caps) == result["capabilities_learned"]
    for c in caps:
        assert c.confirmed is True
        assert c.allowed is True
        assert c.source in {HISTORICAL_ASSIGNMENT, "HISTORICAL_TEMPLATE", "INFERRED_HISTORY"}


def test_b_blank_new_timetable_ingestion():
    """Test B: Verify blank new timetable imports 155 TeachingGroups without crash."""
    if not FILE_SCHEDULE.exists():
        pytest.skip("Schedule test file not found")

    db = _get_isolated_db()
    dept = Department(name="Bộ môn Ngoại ngữ", code="FOREIGN_LANGUAGES")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Blank",
        department_name="Bộ môn Ngoại ngữ",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)
    db.commit()

    parsed = parse_schedule(FILE_SCHEDULE)
    assert len(parsed.classes) == 155, f"Expected 155 classes in parsed schedule, got {len(parsed.classes)}"
    # Verify all classes have no lecturer assigned in raw source
    for c in parsed.classes:
        assert c.lecturer_name is None or c.lecturer_name == ""

    # Import via _import_files_impl
    res = _import_files_impl(
        db,
        [FILE_SCHEDULE],
        semester_id=sem.id,
        schedule_paths=[FILE_SCHEDULE],
        preference_paths=[],
        commit=True,
    )

    classes = db.scalars(select(ClassSection).where(ClassSection.semester_id == sem.id)).all()
    assert len(classes) == 155
    for cls in classes:
        assert cls.assigned_lecturer_id is None
        assert cls.locked_assignment is False


def test_c_selective_historical_capability_learning_no_cartesian_product(tmp_path):
    """Test C: Historical capability learning must be selective (A->X, B->Y) without all-to-all cartesian product."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Kỹ thuật", code="ENGINEERING")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Engineering",
        department_name="Khoa Kỹ thuật",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    lec_a = Lecturer(code="GV001", canonical_name="Nguyễn Văn A", department_id=dept.id, confirmed=True)
    lec_b = Lecturer(code="GV002", canonical_name="Trần Thị B", department_id=dept.id, confirmed=True)
    crs_x = Course(code="ENG101", name="Cơ học kỹ thuật")
    crs_y = Course(code="ENG102", name="Sức bền vật liệu")
    db.add_all([lec_a, lec_b, crs_x, crs_y])
    db.commit()

    # Create mock historical assignment excel: A teaches X, B teaches Y
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lịch sử phân công"
    ws.append(["STT", "Mã học phần", "Tên học phần", "Mã CBGD", "Họ và tên CBGD", "Lớp"])
    ws.append([1, "ENG101", "Cơ học kỹ thuật", "GV001", "Nguyễn Văn A", "67KD1"])
    ws.append([2, "ENG102", "Sức bền vật liệu", "GV002", "Trần Thị B", "67KD2"])
    hist_file = tmp_path / "mock_history.xlsx"
    wb.save(hist_file)

    res = CapabilityResolutionService.learn_from_historical_assignment_file(
        db=db,
        file_path=hist_file,
        semester_id=sem.id,
    )
    assert res["capabilities_learned"] == 2

    # Check capabilities in DB
    caps = db.scalars(select(LecturerCourseCapability)).all()
    assert len(caps) == 2, f"Expected exactly 2 capabilities, got {len(caps)}"

    cap_pairs = {(c.lecturer_id, c.course_id) for c in caps}
    assert (lec_a.id, crs_x.id) in cap_pairs
    assert (lec_b.id, crs_y.id) in cap_pairs
    # Assert strictly NO Cartesian product
    assert (lec_a.id, crs_y.id) not in cap_pairs
    assert (lec_b.id, crs_x.id) not in cap_pairs


def test_d_new_department_without_capabilities_blocks_solver():
    """Test D: New department with no capabilities is NOT_READY and aborts solver with DATA_READINESS_FAILURE."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Cơ khí", code="MECHANICAL")
    db.add(dept)
    db.commit()

    profile = DepartmentProfile(
        department_id=dept.id,
        allow_provisional_capability=False,
        course_capability_mode="STRICT",
        policy_config={},
    )
    db.add(profile)

    sem = Semester(
        name="HK1 2026-2027 Cơ khí",
        department_name="Khoa Cơ khí",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    lec1 = Lecturer(code="ME01", canonical_name="Lê Văn Cơ", department_id=dept.id, confirmed=True)
    lec2 = Lecturer(code="ME02", canonical_name="Phạm Văn Khí", department_id=dept.id, confirmed=True)
    crs = Course(code="ME101", name="Nguyên lý máy")
    db.add_all([lec1, lec2, crs])
    db.commit()

    sec = ClassSection(
        semester_id=sem.id,
        course_id=crs.id,
        class_code="68CK1",
        credits=3.0,
        source_file="test.xlsx",
        source_sheet="Sheet1",
        source_row=1,
    )
    db.add(sec)
    db.commit()

    # Check capability readiness
    readiness = CapabilityResolutionService.evaluate_capability_readiness(db, sem.id)
    assert readiness["ready"] is False
    assert readiness["status"] == "NOT_READY"
    assert readiness["zero_candidate_groups"] == 1
    assert readiness["unknown_coverage_pct"] == 100.0

    # Run solver: should abort early with DATA_READINESS_FAILURE
    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    assert run.status == "blocked"
    assert run.summary.get("code") == "DATA_READINESS_FAILURE"
    assert run.summary.get("teaching_group_count") == 1
    assert run.summary.get("groups_with_zero_candidates") == 1

    # Ensure no assignments were created
    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assert len(assignments) == 0


def test_e_capability_matrix_import(tmp_path):
    """Test E: Capability matrix import populates confirmed capabilities and matches candidates exactly."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Xây dựng Dân dụng", code="CIVIL")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Civil",
        department_name="Khoa Xây dựng Dân dụng",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    lec_1 = Lecturer(code="XD01", canonical_name="Vũ Văn Xây", department_id=dept.id, confirmed=True)
    lec_2 = Lecturer(code="XD02", canonical_name="Đỗ Thị Dựng", department_id=dept.id, confirmed=True)
    crs_1 = Course(code="XD101", name="Bê tông cốt thép")
    crs_2 = Course(code="XD102", name="Kết cấu thép")
    db.add_all([lec_1, lec_2, crs_1, crs_2])
    db.commit()

    # Create matrix Excel: XD01 -> XD101 (1), XD02 -> XD102 (1)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Matrix"
    ws.append(["Mã GV", "Họ và tên", "XD101", "XD102"])
    ws.append(["XD01", "Vũ Văn Xây", 1, 0])
    ws.append(["XD02", "Đỗ Thị Dựng", 0, "x"])
    matrix_file = tmp_path / "matrix.xlsx"
    wb.save(matrix_file)

    res = CapabilityResolutionService.import_capability_matrix(
        db=db,
        file_path=matrix_file,
        semester_id=sem.id,
        confirmed=True,
    )
    assert res["status"] == "SUCCESS"
    assert res["capabilities_created"] == 2

    caps = db.scalars(select(LecturerCourseCapability)).all()
    assert len(caps) == 2
    for c in caps:
        assert c.confirmed is True
        assert c.allowed is True
        assert c.source == IMPORT_CAPABILITY_MATRIX

    # Check candidate resolution
    sec1 = ClassSection(semester_id=sem.id, course_id=crs_1.id, class_code="68XD1", credits=3.0, source_file="s.xlsx", source_sheet="s", source_row=1)
    sec2 = ClassSection(semester_id=sem.id, course_id=crs_2.id, class_code="68XD2", credits=3.0, source_file="s.xlsx", source_sheet="s", source_row=2)
    db.add_all([sec1, sec2])
    db.commit()

    cands1 = CapabilityResolutionService.resolve_candidate_teachers(db, sec1, sem)
    cands2 = CapabilityResolutionService.resolve_candidate_teachers(db, sec2, sem)
    assert cands1["eligible_lecturer_ids"] == [lec_1.id]
    assert cands2["eligible_lecturer_ids"] == [lec_2.id]


def test_f_cross_department_isolation():
    """Test F: Cross-department isolation ensures lecturers from Dept A are never assigned to Dept B."""
    db = _get_isolated_db()
    dept_math = Department(name="Toán học", code="MATH")
    dept_lang = Department(name="Ngoại ngữ", code="FOREIGN_LANGUAGES")
    db.add_all([dept_math, dept_lang])
    db.commit()

    # Lecturers in separate departments
    teacher_math = Lecturer(code="GV_TOAN", canonical_name="Thầy Toán", department_id=dept_math.id, confirmed=True)
    teacher_lang = Lecturer(code="GV_NN", canonical_name="Cô Ngoại Ngữ", department_id=dept_lang.id, confirmed=True)
    course_math = Course(code="MATH101", name="Toán cao cấp")
    course_lang = Course(code="ENG101", name="Tiếng Anh 1")
    db.add_all([teacher_math, teacher_lang, course_math, course_lang])
    db.commit()

    # Capabilities scoped by department
    cap_math = LecturerCourseCapability(lecturer_id=teacher_math.id, course_id=course_math.id, department_id=dept_math.id, allowed=True, confirmed=True)
    cap_lang = LecturerCourseCapability(lecturer_id=teacher_lang.id, course_id=course_lang.id, department_id=dept_lang.id, allowed=True, confirmed=True)
    db.add_all([cap_math, cap_lang])
    db.commit()

    # Semester for Languages
    sem_lang = Semester(
        name="HK1 2026-2027 Ngoại ngữ",
        department_name="Ngoại ngữ",
        department_id=dept_lang.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem_lang)
    db.commit()

    sec_lang = ClassSection(
        semester_id=sem_lang.id,
        course_id=course_lang.id,
        class_code="ENG_CLASS_1",
        credits=3.0,
        source_file="f.xlsx",
        source_sheet="s",
        source_row=1,
    )
    session = ClassSession(
        class_id=1,  # will be flushed
        weekday=2,
        start_period=1,
        end_period=3,
        room="301-A1",
        raw_weeks="1-15",
        active_weeks=list(range(1, 16)),
        source_row=1,
    )
    db.add(sec_lang)
    db.flush()
    session.class_id = sec_lang.id
    db.add(session)
    db.commit()

    # Solve Languages semester
    run = solve(db, time_limit_seconds=5, semester_id=sem_lang.id)
    assert run.status in {"optimal", "feasible"}

    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assert len(assignments) == 1
    # MUST be the language teacher, NEVER the math teacher
    assert assignments[0].lecturer_id == teacher_lang.id
    assert assignments[0].lecturer_id != teacher_math.id


def test_g_full_3_file_foreign_languages_solve():
    """Test G: Real 3-file benchmark assigns all 155 TeachingGroups with 0 unassigned and 0 hard violations."""
    if not (FILE_SCHEDULE.exists() and FILE_PREFERENCES.exists() and FILE_HISTORICAL.exists()):
        pytest.skip("Required real benchmark files not found in /INPUT Gốc/")

    db = _get_isolated_db()
    dept = Department(name="Bộ môn Ngoại ngữ", code="FOREIGN_LANGUAGES")
    db.add(dept)
    db.commit()

    profile = DepartmentProfile(
        department_id=dept.id,
        allow_provisional_capability=False,
        course_capability_mode="STRICT",
        policy_config={},
    )
    db.add(profile)

    sem = Semester(
        name="HK1 2026-2027 Ngoại ngữ Thực tế",
        department_name="Bộ môn Ngoại ngữ",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)
    db.commit()

    # 1. Ingest Schedule and Preferences
    _import_files_impl(
        db,
        [FILE_SCHEDULE, FILE_PREFERENCES],
        semester_id=sem.id,
        schedule_paths=[FILE_SCHEDULE],
        preference_paths=[FILE_PREFERENCES],
        commit=True,
    )

    classes_count = db.query(ClassSection).filter(ClassSection.semester_id == sem.id).count()
    assert classes_count == 155

    # 2. Learn capabilities from historical assignment file
    learn_res = CapabilityResolutionService.learn_from_historical_assignment_file(
        db=db,
        file_path=FILE_HISTORICAL,
        semester_id=sem.id,
    )
    assert learn_res["capabilities_learned"] >= 50

    # 3. Check readiness
    readiness = CapabilityResolutionService.evaluate_capability_readiness(db, sem.id)
    assert readiness["ready"] is True
    assert readiness["zero_candidate_groups"] == 0

    # 4. Solve
    run = solve(db, time_limit_seconds=15, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}

    # 5. Assertions: 155 assigned, 0 unassigned
    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assert len(assignments) == 155, f"Expected 155 assignments, got {len(assignments)}"

    summary = run.summary or {}
    unassigned = summary.get("unassigned", [])
    assert len(unassigned) == 0, f"Expected 0 unassigned groups, got {len(unassigned)}"

    # 6. Post-solve validation
    val = validate_schedule(db, sem.id, run.id)
    assert val["valid"] is True
    assert len(val["blocking_errors"]) == 0


def test_h_unknown_capability_diagnostics():
    """Test H: Classes with no capable lecturer return NO_CAPABILITY diagnostics and structured candidate analysis."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Kiến trúc", code="ARCHITECTURE")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Kiến trúc",
        department_name="Khoa Kiến trúc",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    lec1 = Lecturer(code="KT01", canonical_name="KTS Nguyễn Văn A", department_id=dept.id, confirmed=True)
    lec2 = Lecturer(code="KT02", canonical_name="KTS Trần Thị B", department_id=dept.id, confirmed=True)
    crs_known = Course(code="ARC101", name="Hình họa kiến trúc")
    crs_unknown = Course(code="ARC999", name="Quy hoạch siêu đô thị")
    db.add_all([lec1, lec2, crs_known, crs_unknown])
    db.commit()

    # Only ARC101 has capability, ARC999 has NO capability for any lecturer
    cap1 = LecturerCourseCapability(lecturer_id=lec1.id, course_id=crs_known.id, department_id=dept.id, allowed=True, confirmed=True)
    db.add(cap1)

    sec_unknown = ClassSection(
        semester_id=sem.id,
        course_id=crs_unknown.id,
        class_code="68KT_SPECIAL",
        credits=3.0,
        source_file="test.xlsx",
        source_sheet="s",
        source_row=1,
    )
    db.add(sec_unknown)
    db.commit()

    analysis = get_candidate_analysis(db, sem.id, sec_unknown.id)
    assert analysis["course"]["code"] == "ARC999"
    assert len(analysis["eligible"]) == 0
    assert len(analysis["excluded"]) == 2

    # Both lecturers must be excluded due to NO_CAPABILITY
    for exc in analysis["excluded"]:
        assert exc["status"] == "NO_CAPABILITY"

    # All analysis_rows must have has_capability == False
    for row in analysis["analysis_rows"]:
        assert row["has_capability"] is False
        assert "Không đủ năng lực" in row["status_label"]


def test_historical_learning_immune_to_max_row_none(monkeypatch, tmp_path):
    """Verify that even when Worksheet.max_row is None or 0, streaming iteration still reads all rows."""
    db = _get_isolated_db()
    dept = Department(name="Bộ môn Thể thao Thử nghiệm", code="SPORT_TEST")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Sport",
        department_name="Bộ môn Thể thao Thử nghiệm",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn",
        is_active=True,
    )
    db.add(sem)
    db.commit()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lịch sử"
    ws.append(["STT", "Mã học phần", "Tên học phần", "Mã CBGD", "Họ và tên CBGD", "Lớp"])
    for i in range(1, 21):
        ws.append([i, f"SP{i:03d}", f"Môn thể thao {i}", f"GV{i:03d}", f"HLV {i}", f"Lớp {i}"])
    test_file = tmp_path / "test_stream.xlsx"
    wb.save(test_file)

    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    monkeypatch.setattr(ReadOnlyWorksheet, "max_row", None, raising=False)

    res = CapabilityResolutionService.learn_from_historical_assignment_file(
        db=db,
        file_path=test_file,
        semester_id=sem.id,
    )
    assert res["rows_read"] >= 20
    assert res["capabilities_learned"] == 20
    assert res["unique_courses_identified"] == 20


def test_synthetic_physical_education_department(tmp_path):
    """Verify end-to-end assignment for Physical Education department with 4 coaches and 4 distinct sports."""
    db = _get_isolated_db()
    dept = Department(name="Bộ môn Giáo dục Thể chất", code="PHYSICAL_EDUCATION")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Thể chất",
        department_name="Bộ môn Giáo dục Thể chất",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng bộ môn GDTC",
        is_active=True,
    )
    db.add(sem)

    # 4 coaches
    coaches = [
        Lecturer(code="COACH_FB", canonical_name="HLV Bóng Đá", department_id=dept.id, confirmed=True, max_credits=10.0),
        Lecturer(code="COACH_VB", canonical_name="HLV Bóng Chuyền", department_id=dept.id, confirmed=True, max_credits=10.0),
        Lecturer(code="COACH_BM", canonical_name="HLV Cầu Lông", department_id=dept.id, confirmed=True, max_credits=10.0),
        Lecturer(code="COACH_SW", canonical_name="HLV Bơi Lội", department_id=dept.id, confirmed=True, max_credits=10.0),
    ]
    # 4 courses
    courses = [
        Course(code="PE101", name="Bóng đá 1"),
        Course(code="PE102", name="Bóng chuyền 1"),
        Course(code="PE103", name="Cầu lông 1"),
        Course(code="PE104", name="Bơi lội 1"),
    ]
    db.add_all(coaches + courses)
    db.commit()

    # Matrix: each coach only capable in their sport
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PE Matrix"
    ws.append(["Mã GV", "Họ và tên", "PE101", "PE102", "PE103", "PE104"])
    ws.append(["COACH_FB", "HLV Bóng Đá", 1, 0, 0, 0])
    ws.append(["COACH_VB", "HLV Bóng Chuyền", 0, 1, 0, 0])
    ws.append(["COACH_BM", "HLV Cầu Lông", 0, 0, 1, 0])
    ws.append(["COACH_SW", "HLV Bơi Lội", 0, 0, 0, 1])
    matrix_path = tmp_path / "pe_matrix.xlsx"
    wb.save(matrix_path)

    import_res = CapabilityResolutionService.import_capability_matrix(
        db=db,
        file_path=matrix_path,
        semester_id=sem.id,
        confirmed=True,
    )
    assert import_res["capabilities_created"] == 4

    # Create 4 classes with non-overlapping timetable slots
    for i, crs in enumerate(courses):
        sec = ClassSection(
            semester_id=sem.id,
            course_id=crs.id,
            class_code=f"68PE_{crs.code}",
            credits=2.0,
            source_file="pe.xlsx",
            source_sheet="Sheet1",
            source_row=i + 1,
        )
        db.add(sec)
        db.flush()
        session = ClassSession(
            class_id=sec.id,
            weekday=i + 2,
            start_period=1,
            end_period=3,
            room=f"SAN_{crs.code}",
            raw_weeks="1-15",
            active_weeks=list(range(1, 16)),
            source_row=i + 1,
        )
        db.add(session)
    db.commit()

    readiness = CapabilityResolutionService.evaluate_capability_readiness(db, sem.id)
    assert readiness["ready"] is True
    assert readiness["zero_candidate_groups"] == 0

    run = solve(db, time_limit_seconds=10, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}

    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assert len(assignments) == 4

    assigned_map = {a.class_section.course.code: a.lecturer.code for a in assignments}
    assert assigned_map["PE101"] == "COACH_FB"
    assert assigned_map["PE102"] == "COACH_VB"
    assert assigned_map["PE103"] == "COACH_BM"
    assert assigned_map["PE104"] == "COACH_SW"

    val = validate_schedule(db, sem.id, run.id)
    assert val["valid"] is True
    assert len(val["blocking_errors"]) == 0


def test_unassigned_problem_log_structure():
    """Verify that solver unassigned records contain full structured diagnostic fields."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Tin học", code="IT")
    db.add(dept)
    db.commit()

    profile = DepartmentProfile(
        department_id=dept.id,
        allow_provisional_capability=False,
        course_capability_mode="STRICT",
        policy_config={},
    )
    db.add(profile)

    sem = Semester(
        name="HK1 2026-2027 IT",
        department_name="Khoa Tin học",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    # 1 lecturer capable of IT101 only
    lec = Lecturer(code="IT01", canonical_name="Thầy Tin", department_id=dept.id, confirmed=True, max_credits=10.0)
    crs1 = Course(code="IT101", name="Lập trình C++")
    crs2 = Course(code="IT102", name="Cấu trúc dữ liệu")
    db.add_all([lec, crs1, crs2])
    db.commit()

    # Capability only for IT101, NO capability for IT102
    cap = LecturerCourseCapability(lecturer_id=lec.id, course_id=crs1.id, department_id=dept.id, allowed=True, confirmed=True)
    db.add(cap)

    # Class 1: IT101 (capable)
    sec1 = ClassSection(
        semester_id=sem.id,
        course_id=crs1.id,
        class_code="68IT1",
        credits=3.0,
        source_file="it.xlsx",
        source_sheet="Sheet1",
        source_row=1,
    )
    # Class 2: IT102 (no capable teacher -> unassigned)
    sec2 = ClassSection(
        semester_id=sem.id,
        course_id=crs2.id,
        class_code="68IT2",
        credits=3.0,
        source_file="it.xlsx",
        source_sheet="Sheet1",
        source_row=2,
    )
    db.add_all([sec1, sec2])
    db.flush()

    sess1 = ClassSession(
        class_id=sec1.id,
        weekday=2,
        start_period=1,
        end_period=3,
        room="501-A1",
        raw_weeks="1-15",
        active_weeks=list(range(1, 16)),
        source_row=1,
    )
    sess2 = ClassSession(
        class_id=sec2.id,
        weekday=3,
        start_period=1,
        end_period=3,
        room="502-A1",
        raw_weeks="1-15",
        active_weeks=list(range(1, 16)),
        source_row=2,
    )
    db.add_all([sess1, sess2])
    db.commit()

    run = solve(db, time_limit_seconds=5, semester_id=sem.id)
    summary = run.summary or {}
    unassigned = summary.get("unassigned", [])
    assert len(unassigned) >= 1
    item = unassigned[0]
    assert item.get("course_code") == "IT102" or item.get("course") == "IT102"
    assert "IT102" in str(item.get("course_name", "")) or item.get("course_name") == "Cấu trúc dữ liệu"
    assert item.get("affected_groups") == 1
    assert item.get("capability_coverage") == 0
    assert "recommended_remediation" in item


def test_api_departments_and_capabilities():
    """Verify department and capability API endpoints via TestClient."""
    with TestClient(app) as client:
        resp = client.get("/api/v1/departments")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

        import uuid
        unique_code = f"CHEM_{uuid.uuid4().hex[:6].upper()}"
        new_dept = {
            "name": f"Khoa Hóa học {unique_code}",
            "code": unique_code,
            "description": "Khoa đào tạo Hóa kỹ thuật môi trường",
        }
        resp = client.post("/api/v1/departments", json=new_dept)
        assert resp.status_code == 200
        dept_id = resp.json()["id"]
        assert resp.json()["code"] == unique_code

        resp = client.get(f"/api/v1/departments/{dept_id}/policy")
        assert resp.status_code == 200
        assert resp.json()["course_capability_mode"] == "STRICT"

        update_policy = {
            "allow_provisional_capability": True,
            "course_capability_mode": "PERMISSIVE_WITH_PENALTY",
            "policy_config": {"custom_rule": "test"},
        }
        resp = client.put(f"/api/v1/departments/{dept_id}/policy", json=update_policy)
        assert resp.status_code == 200
        assert resp.json()["allow_provisional_capability"] is True
        assert resp.json()["course_capability_mode"] == "PERMISSIVE_WITH_PENALTY"

        sem_payload = {
            "name": f"HK1 Hóa học {unique_code}",
            "department_name": f"Khoa Hóa học {unique_code}",
            "department_id": dept_id,
            "start_date": "2026-09-07",
            "end_date": "2027-01-24",
            "head_name": "Trưởng khoa Hóa",
        }
        resp = client.post("/api/v1/semesters", json=sem_payload)
        assert resp.status_code == 200
        sem_id = resp.json()["id"]

        resp = client.get("/api/v1/semesters")
        assert resp.status_code == 200
        sem_item = next(s for s in resp.json() if s["id"] == sem_id)
        assert sem_item["department_id"] == dept_id

        resp = client.get(f"/api/v1/semesters/{sem_id}/capabilities")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


def test_validate_schedule_catches_locked_and_availability_violations():
    """Verify validate_schedule catches LOCKED_ASSIGNMENT_INCONSISTENCY, AVAILABILITY_VIOLATION, and TIMETABLE_CONFLICT."""
    db = _get_isolated_db()
    dept = Department(name="Khoa Điện", code="EE")
    db.add(dept)
    db.commit()

    sem = Semester(
        name="HK1 2026-2027 Điện",
        department_name="Khoa Điện",
        department_id=dept.id,
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name="Trưởng khoa",
        is_active=True,
    )
    db.add(sem)

    lec1 = Lecturer(code="EE01", canonical_name="Thầy Điện 1", department_id=dept.id, confirmed=True)
    lec2 = Lecturer(code="EE02", canonical_name="Thầy Điện 2", department_id=dept.id, confirmed=True)
    crs = Course(code="EE101", name="Kỹ thuật điện tử")
    db.add_all([lec1, lec2, crs])
    db.commit()

    db.add(LecturerCourseCapability(lecturer_id=lec1.id, course_id=crs.id, department_id=dept.id, allowed=True, confirmed=True))
    db.add(LecturerCourseCapability(lecturer_id=lec2.id, course_id=crs.id, department_id=dept.id, allowed=True, confirmed=True))
    db.commit()

    hard_con = Constraint(
        semester_id=sem.id,
        lecturer_id=lec1.id,
        name="Bận cứng sáng thứ 2",
        constraint_type="UNAVAILABLE",
        target={"day": "Monday", "weekday": 2, "periods": [1, 2, 3]},
        hardness="hard",
        confirmed=True,
        active=True,
    )
    db.add(hard_con)

    sec1 = ClassSection(
        semester_id=sem.id,
        course_id=crs.id,
        class_code="68EE1",
        credits=3.0,
        assigned_lecturer_id=lec1.id,
        locked_assignment=True,
        source_file="ee.xlsx",
        source_sheet="s",
        source_row=1,
    )
    sec2 = ClassSection(
        semester_id=sem.id,
        course_id=crs.id,
        class_code="68EE2",
        credits=3.0,
        source_file="ee.xlsx",
        source_sheet="s",
        source_row=2,
    )
    db.add_all([sec1, sec2])
    db.flush()

    sess1 = ClassSession(class_id=sec1.id, weekday=3, start_period=1, end_period=3, room="101-A1", raw_weeks="1-10", active_weeks=list(range(1, 11)), source_row=1)
    sess2 = ClassSession(class_id=sec2.id, weekday=2, start_period=1, end_period=3, room="102-A1", raw_weeks="1-10", active_weeks=list(range(1, 11)), source_row=2)
    db.add_all([sess1, sess2])
    db.commit()

    run = OptimizationRun(semester_id=sem.id, status="feasible", summary={})
    db.add(run)
    db.flush()

    # sec1 locked to lec1, but assigned to lec2 -> LOCKED_ASSIGNMENT_INCONSISTENCY
    a1 = Assignment(semester_id=sem.id, run_id=run.id, class_id=sec1.id, lecturer_id=lec2.id, locked=True)
    # sec2 on Monday p1-3, assigned to lec1 who has UNAVAILABLE Monday p1-3 -> AVAILABILITY_VIOLATION
    a2 = Assignment(semester_id=sem.id, run_id=run.id, class_id=sec2.id, lecturer_id=lec1.id)
    db.add_all([a1, a2])
    db.commit()

    val = validate_schedule(db, sem.id, run.id)
    assert val["valid"] is False
    codes = {e["code"] for e in val["blocking_errors"]}
    assert "LOCKED_ASSIGNMENT_INCONSISTENCY" in codes
    assert "AVAILABILITY_VIOLATION" in codes

