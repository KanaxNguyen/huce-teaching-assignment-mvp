from __future__ import annotations

import shutil
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Assignment,
    ClassSection,
    Lecturer,
    LecturerSemesterProfile,
    OptimizationRun,
    OutputTemplateProfile,
    Semester,
    Seminar,
)
from app.services.readiness import validate_schedule
from app.services.source_authority import latest_current_run, source_blockers
from app.storage import get_storage_backend

BLUE = "1F5FAA"
PALE_BLUE = "EAF2FB"
NAVY = "102A43"
GRID = Side(style="thin", color="D9E2EC")


def export_latest(
    db: Session,
    output_dir: Path,
    semester_id: int,
    mode: str = "draft",
    export_type: str = "detailed",
    allow_unassigned_override: bool = False,
    override_reason: str = "",
) -> Path:
    if export_type == "matrix":
        return export_matrix(db, output_dir, semester_id, mode=mode, allow_unassigned_override=allow_unassigned_override, override_reason=override_reason)
    run = latest_current_run(db, semester_id)
    if not run:
        raise ValueError("Chưa có kết quả tối ưu để xuất.")
    validation = validate_schedule(db, semester_id, run.id)
    unassigned = (run.summary or {}).get("unassigned", [])
    if mode == "final":
        if any(e.get("code") == "ASSIGNMENT_WITHOUT_VALID_CAPABILITY" for e in validation.get("blocking_errors", [])):
            raise ValueError("FINAL_EXPORT_NOT_READY: tồn tại phân công giảng dạy không có năng lực hợp lệ (ASSIGNMENT_WITHOUT_VALID_CAPABILITY).")
        has_blockers = source_blockers(db, semester_id) or not validation["valid"] or run.status not in {"optimal", "feasible"} or (run.summary or {}).get("code")
        if has_blockers:
            raise ValueError("FINAL_EXPORT_NOT_READY: còn vi phạm hard constraint hoặc problem blocking.")
        if unassigned:
            if not allow_unassigned_override:
                raise ValueError("FINAL_EXPORT_NOT_READY: còn lớp chưa phân công. Cần xử lý hết hoặc sử dụng quyền phê duyệt đặc quyền của Trưởng bộ môn.")
            if not override_reason or not override_reason.strip():
                raise ValueError("OVERRIDE_REASON_REQUIRED: Cần nhập lý do phê duyệt đặc quyền để xuất file khi còn lớp chưa phân công.")
            from app.models.entities import ValidationIssue
            audit_issue = ValidationIssue(
                semester_id=semester_id,
                severity="info",
                code="PRIVILEGED_FINAL_EXPORT_OVERRIDE",
                message=f"Trưởng bộ môn phê duyệt xuất Final khi còn {len(unassigned)} lớp chưa phân: {override_reason.strip()}",
                details={"unassigned_count": len(unassigned), "reason": override_reason.strip()},
                raw_value=override_reason.strip(),
                resolution_status="RESOLVED",
            )
            db.add(audit_issue)
            db.commit()

    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.run_id == run.id)
        .options(
            selectinload(Assignment.lecturer),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
        )
    ).all()
    sections = db.scalars(
        select(ClassSection)
        .where(ClassSection.semester_id == semester_id)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
    ).all()
    profile = db.scalar(
        select(OutputTemplateProfile)
        .where(OutputTemplateProfile.semester_id == semester_id)
        .order_by(OutputTemplateProfile.id.desc())
    )
    if profile:
        try:
            with get_storage_backend().materialize(profile.source_file) as source:
                return _export_template(profile, assignments, sections, output_dir, source=source, fallback_to_original=run.status not in {"optimal", "feasible"})
        except FileNotFoundError as error:
            raise ValueError("EXPORT_TEMPLATE_SOURCE_NOT_FOUND") from error
    if not assignments:
        raise ValueError("Lần tối ưu gần nhất chưa tạo được phân công; không thể xuất file rỗng.")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"huce-teaching-assignments-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    book = Workbook()
    detail = book.active
    detail.title = "Phân công"
    headers = [
        "STT",
        "Mã học phần",
        "Tên môn học",
        "Mã lớp",
        "Lớp ghép",
        "Thứ",
        "Tiết",
        "Phòng",
        "Số TC",
        "Bắt đầu",
        "Kết thúc",
        "Tuần học",
        "Giảng viên",
        "Đã khóa",
    ]
    detail.append(["HUCE — KẾT QUẢ PHÂN CÔNG GIẢNG DẠY"])
    detail.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    detail["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    detail["A1"].fill = PatternFill("solid", fgColor=NAVY)
    detail["A1"].alignment = Alignment(horizontal="center")
    detail.append(headers)
    row_index = 1
    ass_by_class = {a.class_id: a for a in assignments}
    for section in sections:
        assignment = ass_by_class.get(section.id)
        if assignment and assignment.lecturer:
            lec_name = assignment.lecturer.canonical_name
        elif section.assigned_lecturer:
            lec_name = section.assigned_lecturer.canonical_name
        else:
            lec_name = "Chưa phân công"
        is_locked = "Có" if ((assignment and assignment.locked) or section.locked_assignment) else "Không"
        for session in section.sessions:
            detail.append(
                [
                    row_index,
                    section.course.code,
                    section.course.name,
                    section.class_code,
                    section.merged_group_id or "",
                    session.weekday,
                    f"{session.start_period}-{session.end_period}",
                    session.room,
                    section.credits,
                    session.start_date,
                    session.end_date,
                    session.raw_weeks,
                    lec_name,
                    is_locked,
                ]
            )
            row_index += 1

    schedule = book.create_sheet("TKB_Bo_Mon")
    schedule.append(["BẢNG PHÂN CÔNG GIẢNG DẠY — THỜI KHÓA BIỂU BỘ MÔN"])
    schedule.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)
    schedule["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    schedule["A1"].fill = PatternFill("solid", fgColor=NAVY)
    schedule["A1"].alignment = Alignment(horizontal="center")
    schedule.append([])
    schedule.append(["Giảng viên / Thứ", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"])
    by_lecturer: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for assignment in assignments:
        section = assignment.class_section
        for session in section.sessions:
            date_range = ""
            if session.start_date and session.end_date:
                date_range = f"\n[{session.start_date:%d/%m}-{session.end_date:%d/%m}]"
            by_lecturer[assignment.lecturer.canonical_name][session.weekday].append(
                f"{section.course.name} - {section.class_code}\n"
                f"(Tiết {session.start_period}-{session.end_period})\n"
                f"{session.room}{date_range}"
            )
    for lecturer, weekdays in sorted(by_lecturer.items()):
        schedule.append(
            [lecturer] + ["\n----------------\n".join(weekdays.get(day, [])) for day in range(2, 9)]
        )

    for sheet in (detail, schedule):
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A3" if sheet is detail else "B4"
        sheet.auto_filter.ref = sheet.dimensions
        header_row = 2 if sheet is detail else 3
        for cell in sheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=BLUE)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in sheet.iter_rows(min_row=header_row, max_row=sheet.max_row):
            for cell in row:
                cell.border = Border(left=GRID, right=GRID, top=GRID, bottom=GRID)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for index in range(1, sheet.max_column + 1):
            values = [
                str(sheet.cell(row, index).value or "") for row in range(1, min(sheet.max_row, 120) + 1)
            ]
            sheet.column_dimensions[get_column_letter(index)].width = min(
                max(max(map(len, values), default=8) + 2, 10), 34
            )
        for row in range(header_row + 1, sheet.max_row + 1):
            if row % 2 == 0:
                for cell in sheet[row]:
                    cell.fill = PatternFill("solid", fgColor=PALE_BLUE)
        if sheet is schedule:
            for row in range(4, sheet.max_row + 1):
                lines = max(str(sheet.cell(row, col).value or "").count("\n") + 1 for col in range(1, 9))
                sheet.row_dimensions[row].height = min(max(lines * 10.2, 34), 400)
                for cell in sheet[row]:
                    cell.font = Font(name="Arial", size=9, color=NAVY)

    for row in range(3, detail.max_row + 1):
        detail.cell(row, 10).number_format = "yyyy-mm-dd"
        detail.cell(row, 11).number_format = "yyyy-mm-dd"

    book.save(path)
    return path


def _cell(value: object) -> str:
    """Stable comparison for source values; intentionally never guesses."""
    return str(value or "").strip().casefold()


def _periods(value: object) -> tuple[int, ...]:
    """Normalize an Excel period cell without guessing its meaning."""
    return tuple(int(item) for item in re.findall(r"\d+", str(value or "")))


def _template_row_candidates(
    candidates: list[tuple[ClassSection, object]],
    sheet: object,
    row: int,
    columns: dict[str, int],
) -> list[tuple[ClassSection, object]]:
    """Use optional schedule columns to disambiguate a repeated class row.

    A prior-semester output template normally has one row per meeting.  Its
    row numbers cannot be trusted for a newly imported schedule, so course +
    class alone may identify several meetings.  Each recognised schedule
    column narrows the candidate set only when it has a matching value; stale
    room/week values in an old template therefore cannot turn a valid row into
    an unmapped row.
    """
    def narrow(matches: list[tuple[ClassSection, object]]) -> None:
        nonlocal candidates
        if matches:
            candidates = matches

    if "weekday" in columns:
        value = _cell(sheet.cell(row, columns["weekday"]).value)
        if value:
            narrow([item for item in candidates if _cell(item[1].weekday) == value])
    if "periods" in columns:
        value = _periods(sheet.cell(row, columns["periods"]).value)
        if value:
            narrow([
                item for item in candidates
                if _periods(f"{item[1].start_period}-{item[1].end_period}") == value
            ])
    if "room" in columns:
        value = _cell(sheet.cell(row, columns["room"]).value)
        if value:
            narrow([item for item in candidates if _cell(item[1].room) == value])
    if "weeks" in columns:
        value = _cell(sheet.cell(row, columns["weeks"]).value)
        if value:
            narrow([item for item in candidates if _cell(item[1].raw_weeks) == value])
    return candidates


def _export_template(
    profile: OutputTemplateProfile,
    assignments: list[Assignment],
    sections: list[ClassSection],
    output_dir: Path,
    *,
    source: Path | None = None,
    fallback_to_original: bool = True,
) -> Path:
    source = source or Path(profile.source_file)
    if not source.exists():
        raise ValueError("EXPORT_TEMPLATE_SOURCE_NOT_FOUND")
    mappings = profile.mappings or {}
    missing = [field for field in ("course_code", "class_code", "lecturer") if field not in mappings]
    if missing:
        raise ValueError(f"EXPORT_TEMPLATE_MAPPING_MISSING: {', '.join(missing)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"draft-template-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    import openpyxl
    if source.suffix.lower() == ".xls":
        import xlrd
        try:
            xls_book = xlrd.open_workbook(source, formatting_info=True)
        except Exception:
            xls_book = xlrd.open_workbook(source, formatting_info=False)
        book = openpyxl.Workbook()
        book.remove(book.active)
        for s_idx in range(xls_book.nsheets):
            xls_sheet = xls_book.sheet_by_index(s_idx)
            ws = book.create_sheet(title=xls_sheet.name)
            for r in range(xls_sheet.nrows):
                ws.append(xls_sheet.row_values(r))
            for rlo, rhi, clo, chi in getattr(xls_sheet, "merged_cells", []):
                ws.merge_cells(start_row=rlo + 1, end_row=rhi, start_column=clo + 1, end_column=chi)
    elif source.suffix.lower() == ".xlsx":
        shutil.copy2(source, path)
        book = openpyxl.load_workbook(path)
    else:
        raise ValueError("EXPORT_TEMPLATE_FORMAT_UNSUPPORTED")
    sheet = book[profile.source_sheet] if profile.source_sheet in book.sheetnames else book.active
    columns = {name: int(value["column_index"]) for name, value in mappings.items()}

    template_uses_code = any(
        bool(re.match(r"^\[.+\]", str(sheet.cell(r, columns["lecturer"]).value or "").strip()))
        for r in range(profile.header_row + 1, min(sheet.max_row + 1, profile.header_row + 30))
    )

    def _display_name(lec: Lecturer | None) -> str:
        if not lec:
            return "Chưa phân công"
        if template_uses_code and lec.code:
            return f"[{lec.code}]{lec.canonical_name}"
        return lec.canonical_name

    # Assignment snapshots are the export authority.  A missing snapshot is
    # deliberate partial-solver output, and must be visible in a draft.
    assigned = {item.class_id: _display_name(item.lecturer) for item in assignments}
    # A blocked run has no snapshot by design.  Preserve the imported/manual
    # current state in a draft rather than erasing known, locked lecturers.
    if fallback_to_original:
        assigned.update({
            section.id: _display_name(section.assigned_lecturer)
            for section in sections
            if section.id not in assigned and section.assigned_lecturer is not None
        })
    by_source_row: dict[int, list[tuple[ClassSection, object]]] = defaultdict(list)
    by_class_key: dict[tuple[str, str], list[tuple[ClassSection, object]]] = defaultdict(list)
    source_name = source.name.casefold()
    for section in sections:
        for meeting in section.sessions:
            by_class_key[(_cell(section.course.code), _cell(section.class_code))].append((section, meeting))
            # A source row is the strongest identity.  It is only trusted when
            # the workbook name/sheet agree with the imported source.
            if _cell(section.source_file).endswith(source_name) and section.source_sheet == profile.source_sheet:
                by_source_row[meeting.source_row].append((section, meeting))

    seen_sessions: set[tuple[int, int]] = set()
    for row in range(profile.header_row + 1, sheet.max_row + 1):
        key = (_cell(sheet.cell(row, columns["course_code"]).value), _cell(sheet.cell(row, columns["class_code"]).value))
        if not any(key):
            continue
        candidates = by_source_row.get(row, [])
        # Templates from a prior workbook do not necessarily retain source
        # row numbers.  In that case course+class may be used only if it names
        # exactly one meeting; otherwise this is intentionally a hard error.
        if not candidates:
            candidates = by_class_key.get(key, [])
        candidates = [item for item in candidates if (_cell(item[0].course.code), _cell(item[0].class_code)) == key]
        # A prior-semester template can retain classes that are absent from the
        # current semester.  Leave those rows untouched; a template created
        # from the current import is still completeness-checked below through
        # its source-row identity.
        if not candidates:
            continue
        if len(candidates) > 1:
            candidates = _template_row_candidates(candidates, sheet, row, columns)
        # An output row only stores the lecturer.  Multiple meetings of the
        # same TeachingGroup are therefore equivalent here: the domain
        # guarantees they receive one lecturer, and an old template may split
        # a repeated day/period into more rows than the current import.
        if len(candidates) > 1 and len({item[0].id for item in candidates}) == 1:
            candidates = candidates[:1]
        if len(candidates) != 1:
            raise ValueError("EXPORT_SOURCE_ROW_AMBIGUOUS" if len(candidates) > 1 else "EXPORT_SOURCE_ROW_UNMAPPED")
        section, meeting = candidates[0]
        seen_sessions.add((section.id, meeting.id))
        sheet.cell(row, columns["lecturer"]).value = assigned.get(section.id, "Chưa phân công")

    unmatched_sections = [s for s in sections if s.id not in {s_id for s_id, _ in seen_sessions}]
    if unmatched_sections:
        curr_row = sheet.max_row + 1
        sheet.cell(curr_row, 1).value = "DANH SÁCH LỚP BỔ SUNG (NGOÀI TEMPLATE GỐC)"
        sheet.cell(curr_row, 1).font = Font(bold=True)
        for section in unmatched_sections:
            lec_name = assigned.get(section.id, "Chưa phân công")
            for session in section.sessions:
                curr_row += 1
                if "course_code" in columns:
                    sheet.cell(curr_row, columns["course_code"]).value = section.course.code
                if "course_name" in columns:
                    sheet.cell(curr_row, columns["course_name"]).value = section.course.name
                if "class_code" in columns:
                    sheet.cell(curr_row, columns["class_code"]).value = section.class_code
                if "merged_class" in columns:
                    sheet.cell(curr_row, columns["merged_class"]).value = section.merged_group_id or ""
                if "weekday" in columns:
                    sheet.cell(curr_row, columns["weekday"]).value = session.weekday
                if "periods" in columns:
                    sheet.cell(curr_row, columns["periods"]).value = f"{session.start_period}-{session.end_period}"
                if "room" in columns:
                    sheet.cell(curr_row, columns["room"]).value = session.room
                if "credits" in columns:
                    sheet.cell(curr_row, columns["credits"]).value = section.credits
                if "start_date" in columns and session.start_date:
                    sheet.cell(curr_row, columns["start_date"]).value = session.start_date.isoformat() if hasattr(session.start_date, 'isoformat') else str(session.start_date)
                if "end_date" in columns and session.end_date:
                    sheet.cell(curr_row, columns["end_date"]).value = session.end_date.isoformat() if hasattr(session.end_date, 'isoformat') else str(session.end_date)
                if "weeks" in columns:
                    sheet.cell(curr_row, columns["weeks"]).value = session.raw_weeks
                if "lecturer" in columns:
                    sheet.cell(curr_row, columns["lecturer"]).value = lec_name
                seen_sessions.add((section.id, session.id))

    # Do not silently emit an incomplete copy: every meeting represented by
    # this source workbook must be located exactly once.
    expected = {
        (section.id, meeting.id)
        for section in sections
        for meeting in section.sessions
        if _cell(section.source_file).endswith(source_name) and section.source_sheet == profile.source_sheet
    }
    if expected - seen_sessions:
        raise ValueError("EXPORT_SOURCE_ROW_UNMAPPED")
    # Guarantee that every TeachingGroup in sections is represented in the export
    missing_sections = [s for s in sections if s.id not in {s_id for s_id, _ in seen_sessions}]
    if missing_sections:
        raise ValueError(f"EXPORT_TEACHING_GROUPS_OMITTED: {len(missing_sections)} classes missing from export")
    book.save(path)
    return path


def export_matrix(
    db: Session,
    output_dir: Path,
    semester_id: int,
    mode: str = "draft",
    allow_unassigned_override: bool = False,
    override_reason: str = "",
) -> Path:
    run = latest_current_run(db, semester_id)
    if not run:
        raise ValueError("Chưa có kết quả tối ưu để xuất.")
    validation = validate_schedule(db, semester_id, run.id)
    unassigned = (run.summary or {}).get("unassigned", [])
    if mode == "final":
        if any(e.get("code") == "ASSIGNMENT_WITHOUT_VALID_CAPABILITY" for e in validation.get("blocking_errors", [])):
            raise ValueError("FINAL_EXPORT_NOT_READY: tồn tại phân công giảng dạy không có năng lực hợp lệ (ASSIGNMENT_WITHOUT_VALID_CAPABILITY).")
        has_blockers = source_blockers(db, semester_id) or not validation["valid"] or run.status not in {"optimal", "feasible"} or (run.summary or {}).get("code")
        if has_blockers:
            raise ValueError("FINAL_EXPORT_NOT_READY: còn vi phạm hard constraint hoặc problem blocking.")
        if unassigned:
            if not allow_unassigned_override:
                raise ValueError("FINAL_EXPORT_NOT_READY: còn lớp chưa phân công. Cần xử lý hết hoặc sử dụng quyền phê duyệt đặc quyền của Trưởng bộ môn.")
            if not override_reason or not override_reason.strip():
                raise ValueError("OVERRIDE_REASON_REQUIRED: Cần nhập lý do phê duyệt đặc quyền để xuất file khi còn lớp chưa phân công.")
            from app.models.entities import ValidationIssue
            audit_issue = ValidationIssue(
                semester_id=semester_id,
                severity="info",
                code="PRIVILEGED_FINAL_EXPORT_OVERRIDE",
                message=f"Trưởng bộ môn phê duyệt xuất Final ma trận khi còn {len(unassigned)} lớp chưa phân: {override_reason.strip()}",
                details={"unassigned_count": len(unassigned), "reason": override_reason.strip()},
                raw_value=override_reason.strip(),
                resolution_status="RESOLVED",
            )
            db.add(audit_issue)
            db.commit()


    semester = db.get(Semester, semester_id)
    dept_name = semester.department_name if semester and semester.department_name else "Bộ môn"
    sem_name = semester.name if semester else f"Học kỳ {semester_id}"

    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.run_id == run.id)
        .options(
            selectinload(Assignment.lecturer),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
        )
    ).all()

    # Dynamic lecturer determination (User Correction 1)
    participating_profiles = db.scalars(
        select(LecturerSemesterProfile)
        .where(
            LecturerSemesterProfile.semester_id == semester_id,
            LecturerSemesterProfile.participation_status == "ACTIVE",
        )
    ).all()
    active_profile_ids = {p.lecturer_id for p in participating_profiles}

    if active_profile_ids:
        lecturers = db.scalars(
            select(Lecturer)
            .where(Lecturer.id.in_(active_profile_ids))
            .order_by(Lecturer.canonical_name)
        ).all()
    else:
        assigned_lec_ids = {a.lecturer_id for a in assignments}
        lecturers = list(db.scalars(
            select(Lecturer)
            .where((Lecturer.status == "ACTIVE") | (Lecturer.id.in_(assigned_lec_ids)))
            .order_by(Lecturer.canonical_name)
        ).all())
        existing_ids = {l.id for l in lecturers}
        for a in assignments:
            if a.lecturer_id not in existing_ids:
                lecturers.append(a.lecturer)
                existing_ids.add(a.lecturer_id)
        lecturers.sort(key=lambda l: l.canonical_name)

    seminars = db.scalars(
        select(Seminar)
        .where(Seminar.semester_id == semester_id)
    ).all()

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"huce-matrix-timetable-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "TKB_Bo_Mon"

    title = f"BẢNG PHÂN CÔNG GIẢNG DẠY - {dept_name.upper()}"
    sheet.append([title])
    sheet.merge_cells("A1:H1")
    sheet["A1"].font = Font(name="Arial", size=15, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 36

    unique_groups = {a.class_id for a in assignments}
    subtitle = (
        f"{sem_name} · {len(lecturers)} giảng viên · "
        f"{len(assignments)} nhiệm vụ dạy · {len(unique_groups)} nhóm lớp · "
        f"Cập nhật {datetime.now():%d/%m/%Y}"
    )
    sheet.append([subtitle])
    sheet.merge_cells("A2:H2")
    sheet["A2"].font = Font(name="Arial", size=10, italic=True, color="334E68")
    sheet["A2"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[2].height = 22

    headers = ["Giảng viên / Thứ", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
    sheet.append(headers)
    sheet.row_dimensions[3].height = 28
    for col_idx in range(1, 9):
        cell = sheet.cell(3, col_idx)
        cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    by_lecturer: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for assignment in assignments:
        section = assignment.class_section
        for session in section.sessions:
            date_str = ""
            if session.start_date and session.end_date:
                date_str = f"\n[{session.start_date:%d/%m}-{session.end_date:%d/%m}]"
            room_str = f" · {session.room}" if session.room else ""
            block_text = (
                f"{section.course.name} - {section.class_code}\n"
                f"(Tiết {session.start_period}-{session.end_period}{room_str}{date_str})"
            )
            by_lecturer[assignment.lecturer_id][session.weekday].append(block_text)

    for seminar in seminars:
        members = seminar.members or []
        alternatives = seminar.alternatives or []
        for alt in alternatives:
            weekday = alt.get("weekday")
            periods = alt.get("periods") or []
            start_p = alt.get("start_period")
            end_p = alt.get("end_period")
            period_text = ', '.join(map(str,periods)) if periods else (f'{start_p}-{end_p}' if start_p is not None and end_p is not None else 'Chưa xác định')
            if not weekday:
                continue
            sem_text = (
                f"SEMINAR {seminar.name.upper()}\n"
                f"(Tiết {period_text} hàng tuần)\n"
                f"[{seminar.chair_name} chủ trì]"
            )
            for mem in members:
                for lec in lecturers:
                    if mem == lec.id or mem == lec.code or mem == lec.canonical_name:
                        by_lecturer[lec.id][weekday].insert(0, sem_text)

    for row_idx, lecturer in enumerate(lecturers, start=4):
        row_values = [lecturer.canonical_name]
        for weekday in range(2, 9):
            meetings = by_lecturer[lecturer.id].get(weekday, [])
            cell_text = "\n----------------\n".join(meetings)
            row_values.append(cell_text)
        sheet.append(row_values)

    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "B4"

    sheet.column_dimensions["A"].width = 24
    for col_letter in ("B", "C", "D", "E", "F", "G", "H"):
        sheet.column_dimensions[col_letter].width = 34

    for row_num in range(4, sheet.max_row + 1):
        max_lines = max((str(sheet.cell(row_num, col).value or "").count("\n") + 1 for col in range(1, 9)), default=1)
        sheet.row_dimensions[row_num].height = min(max(max_lines * 13.5, 38), 500)
        is_even = (row_num % 2 == 0)
        for col_num in range(1, 9):
            cell = sheet.cell(row_num, col_num)
            cell.font = Font(name="Arial", size=9, color=NAVY, bold=(col_num == 1))
            cell.border = Border(left=GRID, right=GRID, top=GRID, bottom=GRID)
            cell.alignment = Alignment(
                vertical="top",
                horizontal="center" if col_num == 1 else "left",
                wrap_text=True,
            )
            if is_even:
                cell.fill = PatternFill("solid", fgColor=PALE_BLUE)

    book.save(path)
    return path
