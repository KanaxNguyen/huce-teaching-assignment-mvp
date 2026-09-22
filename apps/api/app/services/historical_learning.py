"""Historical reference learning and evidence ingestion service."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Course,
    HistoricalEvidence,
    Lecturer,
    LecturerAlias,
    LecturerCourseCapability,
    OutputTemplateProfile,
)
from app.services.lecturer_master import normalize_identity, resolve_identity


def extract_lecturer_code_and_name(raw_text: str) -> tuple[str | None, str]:
    """Extract code and name from patterns like '[00187]Phạm Đức Thoan' or 'Phạm Đức Thoan'."""
    text = (raw_text or "").strip()
    match = re.match(r"^\[(.*?)\]\s*(.*)$", text)
    if match:
        code = match.group(1).strip()
        name = match.group(2).strip() or code
        return code, name
    return None, text


def learn_from_template_profile(
    db: Session,
    profile: OutputTemplateProfile,
    file_path: Path,
) -> dict[str, Any]:
    """Extract historical evidence from an output template workbook without creating locks or assignments."""
    if not file_path.exists():
        raise FileNotFoundError(f"Template file not found: {file_path}")

    is_xls = file_path.suffix.lower() == ".xls"
    mappings = profile.mappings or {}
    lecturer_col = mappings.get("lecturer", {}).get("column_index")
    course_code_col = mappings.get("course_code", {}).get("column_index")
    course_name_col = mappings.get("course_name", {}).get("column_index")
    class_code_col = mappings.get("class_code", {}).get("column_index")

    evidence_records: list[HistoricalEvidence] = []
    known_lecturers = 0
    new_candidates = 0
    course_capabilities_found = 0
    unique_lecturers: set[str] = set()
    lecturers_with_code: set[str] = set()
    matched_master_set: set[int] = set()
    need_review_set: set[str] = set()

    if is_xls:
        book = xlrd.open_workbook(file_path)
        sheet = book.sheet_by_name(profile.source_sheet) if profile.source_sheet in book.sheet_names() else book.sheet_by_index(0)
        max_r = sheet.nrows

        def get_val(r: int, c: int) -> str:
            if 0 <= c - 1 < sheet.ncols:
                return str(sheet.cell_value(r - 1, c - 1) or "").strip()
    else:
        book = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheet = book[profile.source_sheet] if profile.source_sheet in book.sheetnames else book.active
        rows_cache = list(sheet.iter_rows(values_only=True))
        max_r = len(rows_cache)

        def get_val(r: int, c: int) -> str:
            if 1 <= r <= len(rows_cache):
                row = rows_cache[r - 1]
                if 0 <= c - 1 < len(row):
                    return str(row[c - 1] or "").strip()
            return ""

    header_row = profile.header_row or 1

    if profile.profile_type == "DEPARTMENT_MATRIX" or (profile.preview and "schedule_days" in profile.preview[0]):
        # Matrix layout
        for row_idx in range(header_row + 1, max_r + 1):
            lec_text = get_val(row_idx, lecturer_col or 1)
            if not lec_text or lec_text.lower() in {"giảng viên / thứ", "giang vien / thu", "stt", ""}:
                continue
            code, name = extract_lecturer_code_and_name(lec_text)
            unique_lecturers.add(name or code)
            if code:
                lecturers_with_code.add(name or code)
            lecturer, _ = resolve_identity(db, name or code or "", code)
            status = "KNOWN_LECTURER" if lecturer else "NEW_LECTURER_CANDIDATE"
            if lecturer:
                known_lecturers += 1
                matched_master_set.add(lecturer.id)
            else:
                new_candidates += 1
                need_review_set.add(name or code)
            rec = HistoricalEvidence(
                semester_id=profile.semester_id,
                profile_id=profile.id,
                source_version_id=profile.source_version_id,
                lecturer_id=lecturer.id if lecturer else None,
                source_text=lec_text,
                lecturer_code=code,
                source_row=row_idx,
                source_cell=f"A{row_idx}",
                evidence={"type": "MATRIX_ROW", "name": name, "code": code},
                status=status,
                human_confirmed=False,
            )
            evidence_records.append(rec)
    else:
        # Detailed assignment table layout
        if not lecturer_col:
            return {"evidence_count": 0, "known_lecturers": 0, "new_candidates": 0, "course_capabilities": 0}

        unique_lecturers: set[str] = set()
        lecturers_with_code: set[str] = set()
        matched_master_set: set[int] = set()
        need_review_set: set[str] = set()

        for row_idx in range(header_row + 1, max_r + 1):
            lec_text = get_val(row_idx, lecturer_col)
            if not lec_text or lec_text.lower() in {"chưa phân công", "chua phan cong", "none", "", "giảng viên", "giang vien"}:
                continue
            
            c_code = get_val(row_idx, course_code_col) if course_code_col else ""
            c_name = get_val(row_idx, course_name_col) if course_name_col else ""
            cls_code = get_val(row_idx, class_code_col) if class_code_col else ""

            parts = [p.strip() for p in re.split(r"[\n,]+", lec_text) if p.strip()]
            for part in parts:
                code, name = extract_lecturer_code_and_name(part)
                unique_lecturers.add(name or code or part)
                if code:
                    lecturers_with_code.add(name or code or part)

                lecturer, reason = resolve_identity(db, name or code or "", code)
                status = "KNOWN_LECTURER" if lecturer else "NEW_LECTURER_CANDIDATE"
                if lecturer:
                    known_lecturers += 1
                    matched_master_set.add(lecturer.id)
                    if c_code:
                        course_capabilities_found += 1
                        course = db.scalar(select(Course).where(Course.code == c_code))
                        if not course:
                            course = Course(code=c_code, name=c_name or c_code)
                            db.add(course)
                            db.flush()
                        cap = db.scalar(select(LecturerCourseCapability).where(
                            LecturerCourseCapability.lecturer_id == lecturer.id,
                            LecturerCourseCapability.course_id == course.id,
                        ))
                        if not cap:
                            db.add(LecturerCourseCapability(
                                lecturer_id=lecturer.id,
                                course_id=course.id,
                                department_id=lecturer.department_id,
                                allowed=True,
                                confirmed=True,
                                source="HISTORICAL_TEMPLATE",
                                confidence=0.95,
                                evidence={"file": file_path.name, "row": row_idx, "class_code": cls_code},
                            ))
                else:
                    new_candidates += 1
                    need_review_set.add(name or code or part)

                rec = HistoricalEvidence(
                    semester_id=profile.semester_id,
                    profile_id=profile.id,
                    source_version_id=profile.source_version_id,
                    lecturer_id=lecturer.id if lecturer else None,
                    source_text=part,
                    lecturer_code=code,
                    source_row=row_idx,
                    source_cell=f"R{row_idx}C{lecturer_col}",
                    evidence={
                        "type": "ASSIGNMENT_ROW",
                        "name": name,
                        "code": code,
                        "course_code": c_code,
                        "course_name": c_name,
                        "class_code": cls_code,
                    },
                    status=status,
                    human_confirmed=False,
                )
                evidence_records.append(rec)

    if evidence_records:
        db.add_all(evidence_records)
        db.commit()

    return {
        "scope": "FULL_FILE_HISTORICAL_LEARNING",
        "workbook_rows": max_r,
        "evidence_source_rows": len({e.source_row for e in evidence_records}),
        "learned_fields": ["identity"] if profile.profile_type == "DEPARTMENT_MATRIX" else ["identity", "course", "class"],
        "not_learned_fields": ["time", "room", "week", "date"],
        "evidence_count": len(evidence_records),
        "total_lecturers": len(unique_lecturers) or known_lecturers,
        "with_code": len(lecturers_with_code),
        "known_lecturers": known_lecturers,
        "matched_master": len(matched_master_set) or known_lecturers,
        "need_review": len(need_review_set),
        "new_candidates": new_candidates,
        "course_capabilities": course_capabilities_found,
    }
