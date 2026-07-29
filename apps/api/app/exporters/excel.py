from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection, OptimizationRun

BLUE = "1F5FAA"
PALE_BLUE = "EAF2FB"
NAVY = "102A43"
GRID = Side(style="thin", color="D9E2EC")


def export_latest(db: Session, output_dir: Path) -> Path:
    run = db.scalars(select(OptimizationRun).order_by(OptimizationRun.id.desc())).first()
    if not run:
        raise ValueError("Chưa có kết quả tối ưu để xuất.")
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.run_id == run.id)
        .options(
            selectinload(Assignment.lecturer),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
        )
    ).all()
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

    schedule = book.create_sheet("TKB giảng viên")
    schedule.append(["GIẢNG VIÊN / THỨ", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"])
    by_lecturer: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for assignment in assignments:
        section = assignment.class_section
        for session in section.sessions:
            by_lecturer[assignment.lecturer.canonical_name][session.weekday].append(
                f"{section.course.name} — {section.class_code}\n"
                f"Tiết {session.start_period}-{session.end_period} · {session.room}"
            )
    for lecturer, weekdays in sorted(by_lecturer.items()):
        schedule.append([lecturer] + ["\n────────\n".join(weekdays.get(day, [])) for day in range(2, 9)])

    for sheet in (detail, schedule):
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A3" if sheet is detail else "B2"
        sheet.auto_filter.ref = sheet.dimensions
        header_row = 2 if sheet is detail else 1
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
            for row in range(2, sheet.max_row + 1):
                lines = max(str(sheet.cell(row, col).value or "").count("\n") + 1 for col in range(1, 9))
                sheet.row_dimensions[row].height = min(max(lines * 11, 30), 180)

    for row in range(3, detail.max_row + 1):
        detail.cell(row, 10).number_format = "yyyy-mm-dd"
        detail.cell(row, 11).number_format = "yyyy-mm-dd"

    book.save(path)
    return path
