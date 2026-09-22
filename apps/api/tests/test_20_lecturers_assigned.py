from datetime import date
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.entities import Semester, Lecturer, LecturerCourseCapability, Assignment
from app.services.importer import _import_files_impl
from app.optimization.solver import solve
from app.parsers.preferences import parse_preference_workbook, detect_preference_format

WORKBOOK_PATH = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chi_Tiet.xlsx')
BACKUP_PATH = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chi_Tiet_backup.xlsx')
SCHEDULE_PATH = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx')

def test_chi_tiet_workbook_structure_and_parse():
    assert detect_preference_format(WORKBOOK_PATH) == "GRID_V3"
    result = parse_preference_workbook(WORKBOOK_PATH)
    assert result.format == "GRID_V3"
    assert len(result.drafts) == 74
    names = {d.canonical_name for d in result.drafts}
    assert len(names) == 20
    assert "Nguyễn Mai Hồng" in names or "Mai Hồng" in names
    assert "Nguyễn Văn Tuyên" in names or "Tuyên" in names
    assert "Nguyễn Thị Thuần" in names or "Cô Nguyễn Thị Thuần" in names

def test_backup_workbook_structure_and_parse():
    assert detect_preference_format(BACKUP_PATH) == "GRID_V3"
    result = parse_preference_workbook(BACKUP_PATH)
    assert result.format == "GRID_V3"
    assert len(result.drafts) == 74
    names = {d.canonical_name for d in result.drafts}
    assert len(names) == 20

def test_fresh_import_and_solve_all_20_lecturers_assigned():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = Session(engine)

    sem = Semester(
        name='Test HK1 2026-2027',
        department_name='Bộ môn Toán học',
        start_date=date(2026, 9, 7),
        end_date=date(2027, 1, 24),
        head_name='Phạm Đức Thoan',
        is_active=True,
    )
    db.add(sem)
    db.commit()

    res = _import_files_impl(
        db,
        [SCHEDULE_PATH, WORKBOOK_PATH],
        semester_id=sem.id,
        schedule_paths=[SCHEDULE_PATH],
        preference_paths=[WORKBOOK_PATH],
        commit=True,
    )

    assert res["summary"]["classes"] > 0
    lecturers = db.scalars(select(Lecturer)).all()
    assert len(lecturers) == 20
    for l in lecturers:
        assert l.status == "ACTIVE"
        assert l.confirmed is True
        caps = db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.lecturer_id == l.id)).all()
        assert len(caps) >= 1, f"Lecturer {l.canonical_name} has no capabilities!"

    run = solve(db, time_limit_seconds=15, confirm_merged=False, semester_id=sem.id)
    assert run.status in {"optimal", "feasible"}

    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assigned_lecturer_ids = {a.lecturer_id for a in assignments}

    for l in lecturers:
        classes_for_lec = [a for a in assignments if a.lecturer_id == l.id]
        assert len(classes_for_lec) > 0, f"Lecturer {l.canonical_name} (ID {l.id}) has 0 assigned classes!"
    
    assert len(assigned_lecturer_ids) == 20
