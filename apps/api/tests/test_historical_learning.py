from datetime import date
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Course,
    HistoricalEvidence,
    Lecturer,
    OutputTemplateProfile,
    Semester,
)
from app.services.historical_learning import learn_from_template_profile


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_historical_learning_extracts_evidence_without_creating_locks_or_assignments(tmp_path):
    with SessionLocal() as db:
        semester = Semester(
            name="HK1 2026-2027",
            department_name="Toán học",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 1, 24),
            head_name="Trưởng bộ môn",
        )
        course = Course(code="391912", name="Toán 6")
        lecturer = Lecturer(code="00187", canonical_name="Phạm Đức Thoan", confirmed=True)
        db.add_all([semester, course, lecturer])
        db.flush()

        # Create an unassigned class section in current semester
        section = ClassSection(
            semester_id=semester.id,
            course_id=course.id,
            class_code="69CLC1",
            source_file="current.xlsx",
            source_sheet="Sheet1",
            source_row=10,
        )
        db.add(section)
        db.commit()
        sid = semester.id
        section_id = section.id

    # Create a mock template workbook
    template_path = tmp_path / "mock_template.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["PHÂN CÔNG GIẢNG DẠY"])
    ws.append([])
    ws.append(["STT", "Mã học phần", "Tên môn học", "Mã lớp học", "Giảng viên"])
    ws.append(["1", "391912", "Toán 6", "69CLC1", "[00187]Phạm Đức Thoan"])
    ws.append(["2", "391912", "Toán 6", "69CLC2", "Nguyễn Chưa Biết"])
    wb.save(template_path)

    with SessionLocal() as db:
        profile = OutputTemplateProfile(
            semester_id=sid,
            source_file=str(template_path),
            source_sheet="Sheet1",
            header_row=3,
            mappings={
                "course_code": {"column_index": 2},
                "course_name": {"column_index": 3},
                "class_code": {"column_index": 4},
                "lecturer": {"column_index": 5},
            },
            missing_fields=[],
            preview=[],
            profile_type="DETAILED_ASSIGNMENT",
        )
        db.add(profile)
        db.commit()

        summary = learn_from_template_profile(db, profile, template_path)
        assert summary["evidence_count"] == 2
        assert summary["known_lecturers"] == 1
        assert summary["new_candidates"] == 1
        assert summary["course_capabilities"] == 1

        # CRITICAL SAFETY: zero assignments and zero locks created
        assert db.scalars(select(Assignment)).all() == []
        current_section = db.get(ClassSection, section_id)
        assert current_section.assigned_lecturer_id is None
        assert not current_section.locked_assignment

        # Verify historical evidence records
        records = db.scalars(select(HistoricalEvidence).where(HistoricalEvidence.semester_id == sid)).all()
        assert len(records) == 2
        by_status = {r.status: r for r in records}
        assert "KNOWN_LECTURER" in by_status
        assert by_status["KNOWN_LECTURER"].lecturer_code == "00187"
        assert by_status["KNOWN_LECTURER"].evidence["course_code"] == "391912"
        assert "NEW_LECTURER_CANDIDATE" in by_status
