from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import shutil

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection, OptimizationRun, OutputTemplateProfile
from app.services.readiness import validate_schedule

BLUE = "1F5FAA"
PALE_BLUE = "EAF2FB"
NAVY = "102A43"
GRID = Side(style="thin", color="D9E2EC")


def export_latest(db: Session, output_dir: Path, semester_id: int, mode: str = "draft") -> Path:
    query = select(OptimizationRun).where(OptimizationRun.semester_id == semester_id).order_by(OptimizationRun.id.desc())
    run = db.scalars(query).first()
    if not run:
        raise ValueError("Chưa có kết quả tối ưu để xuất.")
    validation = validate_schedule(db, semester_id, run.id)
    unassigned = (run.summary or {}).get("unassigned", [])
    if mode == "final" and (not validation["valid"] or unassigned or run.status not in {"optimal", "feasible"} or (run.summary or {}).get("code")):
        raise ValueError("FINAL_EXPORT_NOT_READY: còn vi phạm hard constraint, problem blocking, hoặc lớp chưa phân công.")
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
    profile = db.scalar(select(OutputTemplateProfile).where(OutputTemplateProfile.semester_id == semester_id).order_by(OutputTemplateProfile.id.desc()))
    if profile:
        return _export_template(profile, assignments, sections, output_dir)
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
    for assignment in assignments:
        section = assignment.class_section
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
                    assignment.lecturer.canonical_name,
                    "Có" if assignment.locked else "Không",
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


def _export_template(
    profile: OutputTemplateProfile,
    assignments: list[Assignment],
    sections: list[ClassSection],
    output_dir: Path,
) -> Path:
    source = Path(profile.source_file)
    if not source.exists():
        raise ValueError("EXPORT_TEMPLATE_SOURCE_NOT_FOUND")
    mappings = profile.mappings or {}
    missing = [field for field in ("course_code", "class_code", "lecturer") if field not in mappings]
    if missing:
        raise ValueError(f"EXPORT_TEMPLATE_MAPPING_MISSING: {', '.join(missing)}")
    if source.suffix.lower() != ".xlsx":
        raise ValueError("EXPORT_TEMPLATE_FORMAT_UNSUPPORTED")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"draft-template-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    shutil.copy2(source, path)
    import openpyxl
    book = openpyxl.load_workbook(path)
    sheet = book[profile.source_sheet]
    columns = {name: int(value["column_index"]) for name, value in mappings.items()}
    # Assignment snapshots are the export authority.  A missing snapshot is
    # deliberate partial-solver output, and must be visible in a draft.
    assigned = {item.class_id: item.lecturer.canonical_name for item in assignments}
    # A blocked run has no snapshot by design.  Preserve the imported/manual
    # current state in a draft rather than erasing known, locked lecturers.
    assigned.update({
        section.id: section.assigned_lecturer.canonical_name
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
        if len(candidates) != 1:
            raise ValueError("EXPORT_SOURCE_ROW_AMBIGUOUS" if len(candidates) > 1 else "EXPORT_SOURCE_ROW_UNMAPPED")
        section, meeting = candidates[0]
        seen_sessions.add((section.id, meeting.id))
        sheet.cell(row, columns["lecturer"]).value = assigned.get(section.id, "Chưa phân công")

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
    book.save(path)
    return path
