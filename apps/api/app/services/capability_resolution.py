"""Capability Resolution Service: Authority hierarchy, matrix import, historical learning, and readiness."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Assignment,
    ClassSection,
    Course,
    Department,
    DepartmentProfile,
    HistoricalAssignmentImport,
    Lecturer,
    LecturerCourseCapability,
    OptimizationRun,
    Semester,
)
from app.services.lecturer_master import normalize_identity, resolve_identity

# Authority Source Constants
MANUAL_CONFIRMED = "MANUAL_CONFIRMED"
DEPARTMENT_APPROVED = "DEPARTMENT_APPROVED"
IMPORT_CAPABILITY_MATRIX = "IMPORT_CAPABILITY_MATRIX"
HISTORICAL_ASSIGNMENT = "HISTORICAL_ASSIGNMENT"
HISTORICAL_TEMPLATE = "HISTORICAL_TEMPLATE"
INFERRED_HISTORY = "INFERRED_HISTORY"
PROVISIONAL_DEPARTMENT_POOL = "PROVISIONAL_DEPARTMENT_POOL"
LEGACY = "LEGACY"
DEPARTMENT_BASELINE = "DEPARTMENT_BASELINE"

# Objective Penalty Ranks
PENALTY_CONFIRMED = 0
PENALTY_HISTORICAL = 5
PENALTY_PROVISIONAL = 50


def _plain_text(val: Any) -> str:
    text = unicodedata.normalize("NFC", str(val or "")).strip().casefold()
    text = text.replace("đ", "d")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def extract_code_and_name(raw_text: str) -> tuple[str | None, str]:
    """Extract code and name from patterns like '[00187]Phạm Đức Thoan' or 'Phạm Đức Thoan'."""
    text = (raw_text or "").strip()
    match = re.match(r"^\[(.*?)\]\s*(.*)$", text)
    if match:
        code = match.group(1).strip()
        name = match.group(2).strip() or code
        return code, name
    return None, text


def get_department_profile(db: Session, department_id: int | None) -> DepartmentProfile | None:
    if not department_id:
        return None
    profile = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == department_id))
    if not profile:
        profile = DepartmentProfile(
            department_id=department_id,
            allow_provisional_capability=False,
            course_capability_mode="STRICT",
        )
        db.add(profile)
        db.flush()
    return profile


class CapabilityResolutionService:
    @staticmethod
    def resolve_candidate_teachers(
        db: Session,
        group: ClassSection,
        semester: Semester | None = None,
        policy: DepartmentProfile | None = None,
    ) -> dict[str, Any]:
        """Evaluate candidate teachers for a specific TeachingGroup according to authority hierarchy."""
        course_id = group.course_id
        department_id = semester.department_id if semester else None
        if not policy and department_id:
            policy = get_department_profile(db, department_id)

        query = select(LecturerCourseCapability).where(LecturerCourseCapability.course_id == course_id)
        if department_id:
            query = query.where(
                or_(
                    LecturerCourseCapability.department_id == department_id,
                    LecturerCourseCapability.department_id.is_(None),
                )
            )
        caps = db.scalars(query).all()

        confirmed_ids: set[int] = set()
        historical_ids: set[int] = set()
        provisional_ids: set[int] = set()
        forbidden_ids: set[int] = set()

        for cap in caps:
            if not cap.allowed:
                forbidden_ids.add(cap.lecturer_id)
                continue
            if cap.source == "HYPOTHETICAL_ALL":
                continue
            if cap.confirmed:
                if cap.source in {HISTORICAL_ASSIGNMENT, HISTORICAL_TEMPLATE, INFERRED_HISTORY}:
                    historical_ids.add(cap.lecturer_id)
                else:
                    confirmed_ids.add(cap.lecturer_id)
            else:
                provisional_ids.add(cap.lecturer_id)

        allow_provisional = policy.allow_provisional_capability if policy else False

        eligible = confirmed_ids | historical_ids
        if allow_provisional:
            eligible = eligible | provisional_ids

        eligible = eligible - forbidden_ids
        return {
            "course_id": course_id,
            "confirmed": confirmed_ids,
            "historical": historical_ids,
            "provisional": provisional_ids if allow_provisional else set(),
            "forbidden": forbidden_ids,
            "eligible": eligible,
            "eligible_lecturer_ids": sorted(eligible),
            "allow_provisional": allow_provisional,
        }

    @staticmethod
    def import_capability_matrix(
        db: Session,
        file_path: Path,
        department_id: int | None = None,
        semester_id: int | None = None,
        sheet_name: str | None = None,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        """Import explicit capability matrix from Excel (.xlsx or .xls).
        Supports:
        1. Matrix Layout: rows = Lecturers (col 1: code/name), cols = Course codes/names (header row).
        2. Tabular Layout: columns Lecturer Code/Name, Course Code, Course Name, Allowed.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Capability matrix file not found: {file_path}")

        if not department_id and semester_id:
            semester = db.get(Semester, semester_id)
            if semester and semester.department_id:
                department_id = semester.department_id

        is_xls = file_path.suffix.lower() == ".xls"
        if is_xls:
            book = xlrd.open_workbook(file_path)
            sheet = book.sheet_by_name(sheet_name) if sheet_name and sheet_name in book.sheet_names() else book.sheet_by_index(0)
            rows = [sheet.row_values(r) for r in range(sheet.nrows)]
        else:
            book = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet = book[sheet_name] if sheet_name and sheet_name in book.sheetnames else book.active
            rows = list(sheet.iter_rows(values_only=True))

        if not rows:
            return {"imported": 0, "errors": ["File is empty"]}

        # Detect layout: matrix or tabular
        header_idx = -1
        col_map = {}
        for idx, r in enumerate(rows[:15]):
            plain_r = [_plain_text(c) for c in r]
            if any("ma hp" in c or "ma mon" in c or "course" in c or "hoc phan" in c for c in plain_r) and any(
                "giang vien" in c or "giao vien" in c or "cbgd" in c or "teacher" in c for c in plain_r
            ):
                header_idx = idx
                for c_i, c_val in enumerate(plain_r):
                    if any(k in c_val for k in ["ma hp", "ma mon", "course"]):
                        col_map["course_code"] = c_i
                    elif any(k in c_val for k in ["ten hp", "ten mon", "course name"]):
                        col_map["course_name"] = c_i
                    elif any(k in c_val for k in ["giang vien", "cbgd", "teacher"]):
                        col_map["lecturer"] = c_i
                    elif "ma gv" in c_val or "code" in c_val:
                        col_map["lecturer_code"] = c_i
                break

        imported_count = 0
        updated_count = 0

        if header_idx >= 0 and "course_code" in col_map and "lecturer" in col_map:
            # Tabular import
            for r in rows[header_idx + 1 :]:
                if not any(r):
                    continue
                c_code = str(r[col_map["course_code"]] or "").strip()
                lec_text = str(r[col_map["lecturer"]] or "").strip()
                if not c_code or not lec_text:
                    continue
                lec_code = str(r[col_map.get("lecturer_code", col_map["lecturer"])] or "").strip() if "lecturer_code" in col_map else None
                code_parsed, name_parsed = extract_code_and_name(lec_text)
                final_code = lec_code or code_parsed
                final_name = name_parsed or lec_text

                lecturer, _ = resolve_identity(db, final_name, final_code, semester_id=semester_id)
                if not lecturer and final_code:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.code == final_code))
                if not lecturer and final_name:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.canonical_name == final_name))
                if not lecturer:
                    lecturer = Lecturer(
                        code=final_code,
                        canonical_name=final_name,
                        department_id=department_id,
                        confirmed=True,
                    )
                    db.add(lecturer)
                    db.flush()

                course = db.scalar(select(Course).where(Course.code == c_code))
                if not course:
                    c_name = str(r[col_map["course_name"]] or "").strip() if "course_name" in col_map else c_code
                    course = Course(code=c_code, name=c_name or c_code)
                    db.add(course)
                    db.flush()

                existing = db.scalar(
                    select(LecturerCourseCapability).where(
                        LecturerCourseCapability.lecturer_id == lecturer.id,
                        LecturerCourseCapability.course_id == course.id,
                    )
                )
                if existing:
                    existing.allowed = True
                    existing.confirmed = True
                    existing.source = IMPORT_CAPABILITY_MATRIX
                    existing.confidence = 1.0
                    existing.department_id = department_id or existing.department_id
                    updated_count += 1
                else:
                    db.add(
                        LecturerCourseCapability(
                            lecturer_id=lecturer.id,
                            course_id=course.id,
                            department_id=department_id,
                            allowed=True,
                            confirmed=True,
                            source=IMPORT_CAPABILITY_MATRIX,
                            confidence=1.0,
                            evidence={"import_file": file_path.name, "layout": "tabular"},
                        )
                    )
                    imported_count += 1
        else:
            # Matrix layout: find header row with course codes (columns > 0)
            matrix_header_idx = 0
            for idx, r in enumerate(rows[:15]):
                valid_cells = [str(c).strip() for c in r if str(c).strip()]
                # If row contains 2+ alphanumeric course-code-like tokens
                matches = sum(
                    1 for c in valid_cells
                    if re.search(r"\b([0-9]{5,7}|[A-Za-z0-9_-]{4,10})\b", c)
                    and _plain_text(c) not in {"stt", "no", "tt", "ma gv", "ho va ten", "ho ten", "tong", "ghi chu", "note"}
                )
                if matches >= 2:
                    matrix_header_idx = idx
                    break

            header_row = rows[matrix_header_idx]
            lecturer_code_col: int | None = None
            lecturer_name_col: int | None = None
            stt_cols: set[int] = set()
            ignored_cols: set[int] = set()
            col_to_course: dict[int, Course] = {}

            for c_i, raw_val in enumerate(header_row):
                c_val = str(raw_val or "").strip()
                if not c_val:
                    continue
                p_val = _plain_text(c_val)
                if p_val in {"stt", "no", "tt", "so thu tu"}:
                    stt_cols.add(c_i)
                    continue
                if p_val in {"tong", "tong so", "tong cong", "ghi chu", "note", "gchu"}:
                    ignored_cols.add(c_i)
                    continue
                if any(p_val == k or p_val.startswith(k) for k in ["ma gv", "ma cb", "ma cbgd", "code", "magv", "macbgd", "ma giang vien"]):
                    lecturer_code_col = c_i
                    continue
                if any(p_val == k or p_val.startswith(k) for k in ["ho va ten", "ho ten", "ten gv", "ten cbgd", "giang vien", "cbgd", "can bo giang day", "teacher", "lecturer"]):
                    lecturer_name_col = c_i
                    continue

                # Otherwise, it is a candidate course column
                code_match = re.search(r"\b([0-9]{5,7}|[A-Za-z0-9_-]{4,10})\b", c_val)
                c_code = code_match.group(1) if code_match else c_val
                course = db.scalar(select(Course).where(Course.code == c_code))
                if not course:
                    course = Course(code=c_code, name=c_val)
                    db.add(course)
                    db.flush()
                col_to_course[c_i] = course

            # Process lecturer rows
            for r in rows[matrix_header_idx + 1 :]:
                if not any(r):
                    continue

                raw_code = str(r[lecturer_code_col] or "").strip() if lecturer_code_col is not None and lecturer_code_col < len(r) else ""
                raw_name = str(r[lecturer_name_col] or "").strip() if lecturer_name_col is not None and lecturer_name_col < len(r) else ""

                if lecturer_code_col is None and lecturer_name_col is None:
                    # Fallback when headers do not specify column names
                    min_c = min(col_to_course.keys()) if col_to_course else 1
                    non_stt_cols = [c for c in range(min_c) if c not in stt_cols and c not in ignored_cols]
                    if len(non_stt_cols) == 1:
                        c_idx = non_stt_cols[0]
                        txt = str(r[c_idx] or "").strip() if c_idx < len(r) else ""
                        c_p, n_p = extract_code_and_name(txt)
                        raw_code = c_p or (txt if re.match(r"^[A-Za-z0-9_-]{2,10}$", txt) and " " not in txt else "")
                        raw_name = n_p or txt
                    elif len(non_stt_cols) >= 2:
                        raw_code = str(r[non_stt_cols[0]] or "").strip() if non_stt_cols[0] < len(r) else ""
                        raw_name = str(r[non_stt_cols[1]] or "").strip() if non_stt_cols[1] < len(r) else ""

                if not raw_code and not raw_name:
                    continue

                if _plain_text(raw_code or raw_name) in {"stt", "tong", "tong cong", "total"}:
                    continue

                code = raw_code or None
                name = raw_name or None

                if code and not name:
                    c_p, n_p = extract_code_and_name(code)
                    if n_p != code:
                        code, name = c_p, n_p
                elif name and not code:
                    c_p, n_p = extract_code_and_name(name)
                    if c_p:
                        code, name = c_p, n_p
                    elif re.match(r"^[A-Za-z0-9_-]{2,10}$", name) and " " not in name:
                        code = name

                lecturer = None
                if name or code:
                    lecturer, _ = resolve_identity(db, name or code or "", code=code, semester_id=semester_id)
                if not lecturer and code:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.code == code))
                if not lecturer and name:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.canonical_name == name))

                if not lecturer:
                    lecturer = Lecturer(
                        code=code,
                        canonical_name=name or code or "Lecturer",
                        department_id=department_id,
                        confirmed=True,
                    )
                    db.add(lecturer)
                    db.flush()

                for c_i, course in col_to_course.items():
                    if c_i < len(r):
                        cell_val = _plain_text(r[c_i])
                        if cell_val in {"x", "1", "yes", "co", "true", "v", "ok"}:
                            existing = db.scalar(
                                select(LecturerCourseCapability).where(
                                    LecturerCourseCapability.lecturer_id == lecturer.id,
                                    LecturerCourseCapability.course_id == course.id,
                                )
                            )
                            if existing:
                                existing.allowed = True
                                existing.confirmed = True
                                existing.source = IMPORT_CAPABILITY_MATRIX
                                existing.confidence = 1.0
                                existing.department_id = department_id or existing.department_id
                                updated_count += 1
                            else:
                                db.add(
                                    LecturerCourseCapability(
                                        lecturer_id=lecturer.id,
                                        course_id=course.id,
                                        department_id=department_id,
                                        allowed=True,
                                        confirmed=True,
                                        source=IMPORT_CAPABILITY_MATRIX,
                                        confidence=1.0,
                                        evidence={"import_file": file_path.name, "layout": "matrix"},
                                    )
                                )
                                imported_count += 1

        db.commit()
        return {
            "status": "SUCCESS",
            "imported_new": imported_count,
            "capabilities_created": imported_count,
            "updated_existing": updated_count,
            "capabilities_updated": updated_count,
            "total_capabilities": imported_count + updated_count,
        }

    @staticmethod
    def learn_from_historical_assignment_file(
        db: Session,
        file_path: Path,
        semester_id: int,
        department_id: int | None = None,
        source_version_id: int | None = None,
        sheet_name: str | None = None,
        academic_year: str | None = None,
        semester_code: str | None = None,
    ) -> dict[str, Any]:
        """Learn historical assignments and derive LecturerCourseCapability.
        Robust streaming parser that tolerates read_only=True, title rows, merged headers.
        Independent of OutputTemplateProfile.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Historical file not found: {file_path}")

        semester = db.get(Semester, semester_id)
        if not department_id and semester:
            department_id = semester.department_id

        is_xls = file_path.suffix.lower() == ".xls"
        if is_xls:
            book = xlrd.open_workbook(file_path)
            sheet = book.sheet_by_name(sheet_name) if sheet_name and sheet_name in book.sheet_names() else book.sheet_by_index(0)
            rows = [sheet.row_values(r) for r in range(sheet.nrows)]
            sheet_title = sheet.name
        else:
            book = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet = book[sheet_name] if sheet_name and sheet_name in book.sheetnames else book.active
            rows = list(sheet.iter_rows(values_only=True))
            sheet_title = sheet.title

        if not rows:
            return {"evidence_count": 0, "course_capabilities": 0, "workbook_rows": 0}

        # Auto-detect header row
        header_idx = -1
        col_map: dict[str, int] = {}
        for idx, r in enumerate(rows[:25]):
            plain_r = [_plain_text(c) for c in r]
            has_course = any(
                any(k in c for k in ["ma hoc phan", "ma hp", "ma mon", "course code", "hoc phan", "mon hoc"])
                for c in plain_r
            )
            has_lecturer = any(
                any(k in c for k in ["giang vien", "giao vien", "cbgd", "can bo giang day", "teacher", "lecturer", "gv"])
                for c in plain_r
            )
            if has_course and has_lecturer:
                header_idx = idx
                for c_i, c_val in enumerate(plain_r):
                    if any(k in c_val for k in ["ma hoc phan", "ma hp", "ma mon", "course code", "hoc phan"]):
                        col_map.setdefault("course_code", c_i)
                    elif any(k in c_val for k in ["ten mon hoc", "ten mon", "ten hoc phan", "ten hp", "course name"]):
                        col_map.setdefault("course_name", c_i)
                    elif any(k in c_val for k in ["ma cbgd", "ma gv", "ma can bo", "ma cb"]):
                        col_map.setdefault("lecturer_code", c_i)
                    elif any(k in c_val for k in ["ho va ten", "ho ten", "ten cbgd", "ten gv", "giang vien", "giao vien", "cbgd", "can bo giang day", "teacher", "lecturer"]):
                        col_map.setdefault("lecturer_name", c_i)
                        col_map.setdefault("lecturer", c_i)
                    elif any(k in c_val for k in ["ma lop hoc", "ma lop", "lop hoc", "lop"]):
                        col_map.setdefault("class_code", c_i)
                break

        # Fallback check if headers are on 2 rows (subheaders)
        if header_idx < 0:
            for idx in range(len(rows) - 1):
                combined = []
                r1 = rows[idx]
                r2 = rows[idx + 1]
                max_len = max(len(r1), len(r2))
                for c_i in range(max_len):
                    v1 = _plain_text(r1[c_i]) if c_i < len(r1) else ""
                    v2 = _plain_text(r2[c_i]) if c_i < len(r2) else ""
                    combined.append(f"{v1} {v2}".strip())
                if any(any(k in c for k in ["ma hp", "ma hoc phan", "ma mon"]) for c in combined) and any(
                    any(k in c for k in ["giang vien", "giao vien", "cbgd", "gv"]) for c in combined
                ):
                    header_idx = idx + 1
                    for c_i, c_val in enumerate(combined):
                        if any(k in c_val for k in ["ma hoc phan", "ma hp", "ma mon"]):
                            col_map.setdefault("course_code", c_i)
                        elif any(k in c_val for k in ["ten mon hoc", "ten mon", "ten hp", "ten hoc phan"]):
                            col_map.setdefault("course_name", c_i)
                        elif any(k in c_val for k in ["ma cbgd", "ma gv", "ma cb"]):
                            col_map.setdefault("lecturer_code", c_i)
                        elif any(k in c_val for k in ["ho va ten", "ho ten", "ten cbgd", "ten gv", "giang vien", "giao vien", "cbgd"]):
                            col_map.setdefault("lecturer_name", c_i)
                            col_map.setdefault("lecturer", c_i)
                        elif any(k in c_val for k in ["ma lop", "lop"]):
                            col_map.setdefault("class_code", c_i)
                    break

        if "lecturer" not in col_map:
            if "lecturer_name" in col_map:
                col_map["lecturer"] = col_map["lecturer_name"]
            elif "lecturer_code" in col_map:
                col_map["lecturer"] = col_map["lecturer_code"]

        if header_idx < 0 or "course_code" not in col_map or "lecturer" not in col_map:
            # Diagnostics on failure
            return {
                "error": "CANNOT_DETECT_HEADER_COLUMNS",
                "workbook_rows": len(rows),
                "rows_read": len(rows),
                "detected_columns": list(col_map.keys()),
                "evidence_count": 0,
                "course_capabilities": 0,
                "capabilities_learned": 0,
                "learned_capabilities": 0,
                "unique_lecturers_identified": 0,
                "unique_courses_identified": 0,
            }

        course_code_col = col_map["course_code"]
        lecturer_col = col_map["lecturer"]
        course_name_col = col_map.get("course_name")
        class_code_col = col_map.get("class_code")
        lecturer_name_col = col_map.get("lecturer_name")
        lecturer_code_col = col_map.get("lecturer_code")

        evidence_count = 0
        course_capabilities_count = 0
        unique_lecturers: set[str] = set()
        unique_courses: set[str] = set()
        matched_lecturers: set[int] = set()

        for row_idx in range(header_idx + 1, len(rows)):
            row = rows[row_idx]
            if not row:
                continue

            c_code = str(row[course_code_col] or "").strip() if course_code_col < len(row) else ""
            c_name = str(row[course_name_col] or "").strip() if course_name_col is not None and course_name_col < len(row) else ""
            cls_code = str(row[class_code_col] or "").strip() if class_code_col is not None and class_code_col < len(row) else ""

            if not c_code:
                continue

            # Extract lecturer text and code
            lec_name = str(row[lecturer_name_col] or "").strip() if lecturer_name_col is not None and lecturer_name_col < len(row) else ""
            lec_code = str(row[lecturer_code_col] or "").strip() if lecturer_code_col is not None and lecturer_code_col < len(row) else ""
            lec_text = str(row[lecturer_col] or "").strip() if lecturer_col < len(row) else ""

            if not lec_name and lec_text:
                lec_name = lec_text

            if not lec_name and not lec_code:
                continue

            check_text = (lec_name or lec_code).lower()
            if check_text in {"chưa phân công", "chua phan cong", "none", "", "giảng viên", "giang vien"}:
                continue

            unique_courses.add(c_code)

            # Might have multiple lecturers separated by comma, semicolon, slash or newline
            split_text = lec_name or lec_code
            parts = [p.strip() for p in re.split(r"[\n,;/]+", split_text) if p.strip()]
            for part in parts:
                code_parsed, name_parsed = extract_code_and_name(part)
                cur_code = code_parsed or (lec_code if len(parts) == 1 and lec_code else None)
                cur_name = name_parsed or part

                unique_lecturers.add(cur_name or cur_code or part)
                evidence_count += 1

                lecturer, _ = resolve_identity(db, cur_name or cur_code or "", code=cur_code, semester_id=semester_id)
                if not lecturer and cur_code:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.code == cur_code))
                if not lecturer and cur_name:
                    lecturer = db.scalar(select(Lecturer).where(Lecturer.canonical_name == cur_name))

                if lecturer and not lecturer.department_id and department_id:
                    lecturer.department_id = department_id

                if not lecturer:
                    # Create or register lecturer under the department
                    lecturer = Lecturer(
                        code=cur_code,
                        canonical_name=cur_name or part,
                        department_id=department_id,
                        confirmed=bool(cur_code),
                        source_file=file_path.name,
                    )
                    db.add(lecturer)
                    db.flush()

                matched_lecturers.add(lecturer.id)

                # Ensure Course exists
                course = db.scalar(select(Course).where(Course.code == c_code))
                if not course:
                    course = Course(code=c_code, name=c_name or c_code)
                    db.add(course)
                    db.flush()

                # Upsert capability with source HISTORICAL_ASSIGNMENT
                cap = db.scalar(
                    select(LecturerCourseCapability).where(
                        LecturerCourseCapability.lecturer_id == lecturer.id,
                        LecturerCourseCapability.course_id == course.id,
                    )
                )
                if not cap:
                    db.add(
                        LecturerCourseCapability(
                            lecturer_id=lecturer.id,
                            course_id=course.id,
                            department_id=department_id or lecturer.department_id,
                            allowed=True,
                            confirmed=True,
                            source=HISTORICAL_ASSIGNMENT,
                            confidence=0.95,
                            evidence={
                                "source_file": file_path.name,
                                "source_sheet": sheet_title,
                                "source_row": row_idx + 1,
                                "class_code": cls_code,
                                "course_name": c_name,
                            },
                        )
                    )
                    course_capabilities_count += 1
                else:
                    # Upgrade legacy or baseline to confirmed historical
                    if not cap.confirmed or cap.source in {"DEPARTMENT_BASELINE", "PROVISIONAL_DEPARTMENT_POOL"}:
                        cap.allowed = True
                        cap.confirmed = True
                        cap.source = HISTORICAL_ASSIGNMENT
                        cap.confidence = 0.95

        # Record import in HistoricalAssignmentImport table
        import_record = HistoricalAssignmentImport(
            semester_id=semester_id,
            department_id=department_id,
            source_version_id=source_version_id,
            source_file=file_path.name,
            source_sheet=sheet_title,
            row_count=len(rows),
            learned_capabilities=course_capabilities_count,
            summary={
                "unique_lecturers": len(unique_lecturers),
                "matched_lecturers": len(matched_lecturers),
                "evidence_rows": evidence_count,
            },
        )
        db.add(import_record)
        db.commit()

        return {
            "scope": "FULL_FILE_HISTORICAL_LEARNING",
            "workbook_rows": len(rows),
            "rows_read": len(rows),
            "evidence_count": evidence_count,
            "unique_lecturers": len(unique_lecturers),
            "unique_lecturers_identified": len(unique_lecturers),
            "matched_lecturers": len(matched_lecturers),
            "course_capabilities": course_capabilities_count,
            "capabilities_learned": course_capabilities_count,
            "learned_capabilities": course_capabilities_count,
            "unique_courses_identified": len(unique_courses),
            "source_sheet": sheet_title,
        }

    @staticmethod
    def evaluate_capability_readiness(db: Session, semester_id: int) -> dict[str, Any]:
        """Comprehensive capability readiness check before solving."""
        semester = db.get(Semester, semester_id)
        if not semester:
            raise ValueError(f"Semester {semester_id} not found")

        groups = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
        dept_id = semester.department_id
        # Lecturers belonging to this department (or unassigned department)
        lec_query = select(Lecturer).where(Lecturer.status == "ACTIVE")
        if dept_id is not None:
            lec_query = lec_query.where(
                or_(
                    Lecturer.department_id == dept_id,
                    Lecturer.department_id.is_(None),
                )
            )
        lecturers = db.scalars(lec_query).all()
        active_lec_ids = {l.id for l in lecturers}
        all_courses = {g.course_id: g.course for g in groups if g.course}

        # Capability coverage analysis: ONLY capabilities relevant to this department and its active lecturers
        cap_query = select(LecturerCourseCapability).where(
            or_(
                LecturerCourseCapability.source.is_(None),
                LecturerCourseCapability.source != "HYPOTHETICAL_ALL",
            )
        )
        if dept_id is not None:
            cap_query = cap_query.where(
                or_(
                    LecturerCourseCapability.department_id == dept_id,
                    LecturerCourseCapability.department_id.is_(None),
                )
            )
        capabilities = [
            cap for cap in db.scalars(cap_query).all()
            if cap.lecturer_id in active_lec_ids
        ]

        caps_by_course = defaultdict(list)
        for cap in capabilities:
            caps_by_course[cap.course_id].append(cap)

        courses_with_confirmed = set()
        courses_with_historical = set()
        courses_with_provisional = set()
        courses_with_none = set()

        groups_with_confirmed = 0
        groups_with_historical_only = 0
        groups_with_provisional_only = 0
        groups_with_zero = 0

        courses_without_capability: list[dict[str, Any]] = []

        for c_id, course in all_courses.items():
            c_caps = caps_by_course.get(c_id, [])
            has_conf = any(c.allowed and c.confirmed and c.source not in {HISTORICAL_ASSIGNMENT, HISTORICAL_TEMPLATE, INFERRED_HISTORY} for c in c_caps)
            has_hist = any(c.allowed and c.confirmed and c.source in {HISTORICAL_ASSIGNMENT, HISTORICAL_TEMPLATE, INFERRED_HISTORY} for c in c_caps)
            has_prov = any(c.allowed and not c.confirmed for c in c_caps)

            if has_conf:
                courses_with_confirmed.add(c_id)
            elif has_hist:
                courses_with_historical.add(c_id)
            elif has_prov:
                courses_with_provisional.add(c_id)
            else:
                courses_with_none.add(c_id)
                affected = sum(1 for g in groups if g.course_id == c_id)
                courses_without_capability.append({
                    "course_id": c_id,
                    "course_code": course.code,
                    "course_name": course.name,
                    "affected_groups": affected,
                })

        for g in groups:
            c_caps = caps_by_course.get(g.course_id, [])
            has_conf = any(c.allowed and c.confirmed and c.source not in {HISTORICAL_ASSIGNMENT, HISTORICAL_TEMPLATE, INFERRED_HISTORY} for c in c_caps)
            has_hist = any(c.allowed and c.confirmed and c.source in {HISTORICAL_ASSIGNMENT, HISTORICAL_TEMPLATE, INFERRED_HISTORY} for c in c_caps)
            has_prov = any(c.allowed and not c.confirmed for c in c_caps)

            if has_conf:
                groups_with_confirmed += 1
            elif has_hist:
                groups_with_historical_only += 1
            elif has_prov:
                groups_with_provisional_only += 1
            else:
                groups_with_zero += 1

        total_groups = len(groups)
        total_courses = len(all_courses)

        confirmed_coverage = round(groups_with_confirmed / total_groups * 100, 1) if total_groups else 0
        historical_coverage = round(groups_with_historical_only / total_groups * 100, 1) if total_groups else 0
        provisional_coverage = round(groups_with_provisional_only / total_groups * 100, 1) if total_groups else 0
        unknown_coverage = round(groups_with_zero / total_groups * 100, 1) if total_groups else 0

        ready = groups_with_zero == 0 and total_groups > 0
        status = "READY" if ready else ("CAPABILITY_REVIEW_REQUIRED" if (groups_with_confirmed + groups_with_historical_only) > 0 else "NOT_READY")

        recommendations = []
        if groups_with_zero > 0:
            recommendations.append("Import a previous-semester assignment file to learn capabilities.")
            recommendations.append("Import a capability matrix (Excel/CSV) mapping lecturers to courses.")
            recommendations.append("Manually review and approve capabilities for unassigned courses.")

        return {
            "department_id": semester.department_id,
            "department_name": semester.department_name,
            "total_lecturers": len(lecturers),
            "total_courses": total_courses,
            "total_teaching_groups": total_groups,
            "confirmed_groups": groups_with_confirmed,
            "historical_groups": groups_with_historical_only,
            "provisional_groups": groups_with_provisional_only,
            "zero_candidate_groups": groups_with_zero,
            "confirmed_coverage_pct": confirmed_coverage,
            "historical_coverage_pct": historical_coverage,
            "provisional_coverage_pct": provisional_coverage,
            "unknown_coverage_pct": unknown_coverage,
            "courses_without_capability": courses_without_capability,
            "status": status,
            "ready": ready,
            "recommendations": recommendations,
        }

    @staticmethod
    def list_capabilities(
        db: Session,
        semester_id: int,
        course_id: int | None = None,
        lecturer_id: int | None = None,
        source: str | None = None,
        confirmed: bool | None = None,
        allowed: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List capabilities scoped to semester's department with flexible filtering."""
        semester = db.get(Semester, semester_id)
        dept_id = semester.department_id if semester else None

        query = select(LecturerCourseCapability)
        if dept_id is not None:
            query = query.where(
                or_(
                    LecturerCourseCapability.department_id == dept_id,
                    LecturerCourseCapability.department_id.is_(None),
                )
            )
        if course_id is not None:
            query = query.where(LecturerCourseCapability.course_id == course_id)
        if lecturer_id is not None:
            query = query.where(LecturerCourseCapability.lecturer_id == lecturer_id)
        if source is not None:
            query = query.where(LecturerCourseCapability.source == source)
        if confirmed is not None:
            query = query.where(LecturerCourseCapability.confirmed == confirmed)
        if allowed is not None:
            query = query.where(LecturerCourseCapability.allowed == allowed)

        caps = db.scalars(query).all()
        result = []
        for c in caps:
            result.append({
                "id": c.id,
                "lecturer_id": c.lecturer_id,
                "lecturer_code": c.lecturer.code if c.lecturer else None,
                "lecturer_name": c.lecturer.canonical_name if c.lecturer else None,
                "course_id": c.course_id,
                "course_code": c.course.code if c.course else None,
                "course_name": c.course.name if c.course else None,
                "allowed": c.allowed,
                "confirmed": c.confirmed,
                "source": c.source,
                "confidence": c.confidence,
                "evidence": c.evidence or {},
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return result

    @staticmethod
    def bulk_confirm_capabilities(
        db: Session,
        semester_id: int,
        capability_ids: list[int] | None = None,
        course_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Bulk confirm provisional or historical capabilities."""
        semester = db.get(Semester, semester_id)
        dept_id = semester.department_id if semester else None

        query = select(LecturerCourseCapability).where(LecturerCourseCapability.allowed.is_(True))
        if dept_id is not None:
            query = query.where(
                or_(
                    LecturerCourseCapability.department_id == dept_id,
                    LecturerCourseCapability.department_id.is_(None),
                )
            )
        if capability_ids:
            query = query.where(LecturerCourseCapability.id.in_(capability_ids))
        if course_ids:
            query = query.where(LecturerCourseCapability.course_id.in_(course_ids))

        caps = db.scalars(query).all()
        confirmed_count = 0
        for c in caps:
            if not c.confirmed:
                c.confirmed = True
                c.source = c.source or MANUAL_CONFIRMED
                confirmed_count += 1

        db.commit()
        return {"status": "SUCCESS", "confirmed_count": confirmed_count}

    @staticmethod
    def update_capability(
        db: Session,
        capability_id: int,
        allowed: bool | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any]:
        """Update individual capability record."""
        cap = db.get(LecturerCourseCapability, capability_id)
        if not cap:
            raise ValueError(f"Capability {capability_id} not found")

        if allowed is not None:
            cap.allowed = allowed
        if confirmed is not None:
            cap.confirmed = confirmed
        cap.source = cap.source or MANUAL_CONFIRMED
        db.commit()
        return {
            "id": cap.id,
            "lecturer_id": cap.lecturer_id,
            "course_id": cap.course_id,
            "allowed": cap.allowed,
            "confirmed": cap.confirmed,
            "source": cap.source,
        }
