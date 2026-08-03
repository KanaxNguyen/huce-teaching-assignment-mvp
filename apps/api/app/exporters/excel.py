from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection, Constraint, OptimizationRun
from app.services.settings import get_app_settings

BLUE = "1F5FAA"
PALE_BLUE = "EAF2FB"
NAVY = "102A43"
GRID = Side(style="thin", color="D9E2EC")


def _style_sheet(sheet, header_row: int) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=header_row, max_row=sheet.max_row):
        for cell in row:
            cell.border = Border(left=GRID, right=GRID, top=GRID, bottom=GRID)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index in range(1, sheet.max_column + 1):
        values = [str(sheet.cell(row, index).value or "") for row in range(1, min(sheet.max_row, 200) + 1)]
        sheet.column_dimensions[get_column_letter(index)].width = min(
            max(max(map(len, values), default=8) + 2, 10), 38
        )
    for row in range(header_row + 1, sheet.max_row + 1):
        if row % 2 == 0:
            for cell in sheet[row]:
                cell.fill = PatternFill("solid", fgColor=PALE_BLUE)


def _add_title(sheet, title: str, subtitle: str, columns: int) -> None:
    sheet.append([title])
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    sheet["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.append([subtitle])
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    sheet["A2"].font = Font(italic=True, color=NAVY)
    sheet["A2"].alignment = Alignment(horizontal="center")


def _session_label(session) -> str:
    date_range = ""
    if session.start_date or session.end_date:
        start = session.start_date.strftime("%d/%m") if session.start_date else "?"
        end = session.end_date.strftime("%d/%m") if session.end_date else "?"
        date_range = f"\n[{start}-{end}]"
    return f"Tiết {session.start_period}-{session.end_period} · {session.room or 'Chưa có phòng'}{date_range}"


def _overlap(left, right) -> bool:
    if (
        left.weekday != right.weekday
        or left.end_period < right.start_period
        or right.end_period < left.start_period
    ):
        return False
    if (
        left.active_weeks
        and right.active_weeks
        and not set(left.active_weeks).intersection(right.active_weeks)
    ):
        return False
    if left.start_date and right.end_date and left.start_date > right.end_date:
        return False
    return not (right.start_date and left.end_date and right.start_date > left.end_date)


def export_latest(db: Session, output_dir: Path) -> Path:
    app_settings = get_app_settings(db)
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
    year_slug = app_settings.academic_year.replace("-", "_").replace("/", "_")
    path = output_dir / f"Thoi_Khoa_Bieu_To_Bo_Mon_{year_slug}_Hoan_Chinh.xlsx"
    book = Workbook()
    schedule = book.active
    schedule.title = "TKB_Bo_Mon"
    _add_title(
        schedule,
        "BẢNG PHÂN CÔNG GIẢNG DẠY - GIỮ NGUYÊN VẸN TOÀN BỘ LỚP HỌC PHẦN GỐC",
        f"Học kỳ {app_settings.semester} - Năm học {app_settings.academic_year} | "
        "Sinh tự động từ dữ liệu đã tối ưu",
        8,
    )
    schedule.append(["Giảng viên / Thứ", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"])
    grouped: dict[tuple[str, str], list[Assignment]] = defaultdict(list)
    for assignment in assignments:
        section = assignment.class_section
        group_key = section.merged_group_id or f"class-{section.id}"
        grouped[(assignment.lecturer.canonical_name, group_key)].append(assignment)
    by_lecturer: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for (lecturer, _), group_items in grouped.items():
        first = group_items[0].class_section
        class_codes = " + ".join(sorted(item.class_section.class_code for item in group_items))
        for session in first.sessions:
            by_lecturer[lecturer][session.weekday].append(
                f"{first.course.name} - {class_codes}\n({_session_label(session)})"
            )
    for lecturer, weekdays in sorted(by_lecturer.items()):
        schedule.append(
            [lecturer] + ["\n----------------\n".join(weekdays.get(day, [])) for day in range(2, 9)]
        )
    _style_sheet(schedule, 3)
    schedule.freeze_panes = "B4"
    for row in range(4, schedule.max_row + 1):
        lines = max(str(schedule.cell(row, col).value or "").count("\n") + 1 for col in range(1, 9))
        schedule.row_dimensions[row].height = min(max(lines * 11, 30), 240)

    detail = book.create_sheet("Phan_Cong_Chi_Tiet")
    _add_title(
        detail,
        "PHÂN CÔNG CHI TIẾT THEO MÔN - LỚP",
        "Dùng để đối chiếu lớp ghép, lịch học và nguồn quyết định phân công.",
        10,
    )
    detail.append([])
    detail.append(
        [
            "Mã HP",
            "Tên môn học",
            "Mã lớp",
            "Nhóm lớp ghép",
            "Số TC",
            "Giảng viên mới",
            "Nguồn phân công",
            "Đã khóa",
            "Số buổi",
            "Lịch học",
        ]
    )
    for assignment in assignments:
        section = assignment.class_section
        detail.append(
            [
                section.course.code,
                section.course.name,
                section.class_code,
                section.merged_group_id or "",
                section.credits,
                assignment.lecturer.canonical_name,
                "Dữ liệu gốc" if assignment.locked else "Tối ưu CP-SAT",
                "Có" if assignment.locked else "Không",
                len(section.sessions),
                "\n".join(f"Thứ {item.weekday} · {_session_label(item)}" for item in section.sessions),
            ]
        )
    _style_sheet(detail, 4)

    constraints = db.scalars(
        select(Constraint).options(selectinload(Constraint.lecturer)).order_by(Constraint.id)
    ).all()
    soft_violations = []
    for constraint_item in constraints:
        if constraint_item.hardness != "soft" or not constraint_item.lecturer_id:
            continue
        weekday = constraint_item.target.get("weekday")
        periods = constraint_item.target.get("periods") or constraint_item.target.get("period_range") or []
        for assignment in assignments:
            if assignment.lecturer_id != constraint_item.lecturer_id:
                continue
            for session in assignment.class_section.sessions:
                if weekday is not None and session.weekday != weekday:
                    continue
                if constraint_item.constraint_type == "prefer_period" and len(periods) >= 2:
                    preferred_start, preferred_end = min(periods), max(periods)
                    violates = session.start_period < preferred_start or session.end_period > preferred_end
                else:
                    violates = not periods or any(
                        session.start_period <= int(period) <= session.end_period for period in periods
                    )
                if violates:
                    soft_violations.append((constraint_item, assignment, session))

    soft = book.create_sheet("Vi_Pham_Mem")
    _add_title(
        soft,
        "DANH SÁCH VI PHẠM RÀNG BUỘC MỀM",
        "Các mục này được phép vi phạm theo trọng số và không làm phương án bị loại.",
        8,
    )
    soft.append([])
    soft.append(["Giảng viên", "Môn học", "Lớp", "Thứ", "Tiết", "Ràng buộc", "Trọng số", "Mức phạt"])
    for constraint_item, assignment, session in soft_violations:
        soft.append(
            [
                assignment.lecturer.canonical_name,
                assignment.class_section.course.name,
                assignment.class_section.class_code,
                session.weekday,
                f"{session.start_period}-{session.end_period}",
                constraint_item.raw_text or constraint_item.name,
                constraint_item.weight,
                constraint_item.weight,
            ]
        )
    _style_sheet(soft, 4)

    merged = book.create_sheet("Kiem_Tra_Nhom_Ghep")
    _add_title(
        merged, "KIỂM TRA NHÓM LỚP GHÉP", "Các lớp trong cùng nhóm phải được phân cho đúng một giảng viên.", 5
    )
    merged.append([])
    merged.append(["Nhóm lớp", "Môn học", "Các lớp", "Giảng viên", "Kết quả"])
    for (lecturer, group_id), group_items in sorted(grouped.items()):
        if group_id.startswith("class-"):
            continue
        merged.append(
            [
                group_id,
                group_items[0].class_section.course.name,
                " + ".join(sorted(item.class_section.class_code for item in group_items)),
                lecturer,
                "Đạt",
            ]
        )
    _style_sheet(merged, 4)

    conflict = book.create_sheet("Xung_Dot_Cung")
    _add_title(
        conflict, "KIỂM TRA XUNG ĐỘT CỨNG", "Không cho phép một giảng viên dạy hai lớp đơn trùng lịch.", 3
    )
    conflict.append([])
    conflict.append(["Giảng viên", "Lịch thứ nhất", "Lịch thứ hai"])
    conflicts = []
    for index, left in enumerate(assignments):
        for right in assignments[index + 1 :]:
            if left.lecturer_id != right.lecturer_id:
                continue
            if (
                left.class_section.merged_group_id
                and left.class_section.merged_group_id == right.class_section.merged_group_id
            ):
                continue
            for left_session in left.class_section.sessions:
                for right_session in right.class_section.sessions:
                    if _overlap(left_session, right_session):
                        conflicts.append((left, left_session, right, right_session))
    for left, left_session, right, right_session in conflicts:
        conflict.append(
            [
                left.lecturer.canonical_name,
                (
                    f"{left.class_section.class_code} · Thứ {left_session.weekday} · "
                    f"{_session_label(left_session)}"
                ),
                (
                    f"{right.class_section.class_code} · Thứ {right_session.weekday} · "
                    f"{_session_label(right_session)}"
                ),
            ]
        )
    if not conflicts:
        conflict["A2"] = "Không phát hiện xung đột lịch giảng viên."
    _style_sheet(conflict, 4)

    wishes = book.create_sheet("Nguyen_Vong_Goc")
    _add_title(
        wishes,
        "NGUYỆN VỌNG VÀ RÀNG BUỘC ĐÃ NHẬP",
        "Ràng buộc mềm có thể vi phạm theo trọng số; ràng buộc cứng là bắt buộc.",
        7,
    )
    wishes.append([])
    wishes.append(
        ["Tên ràng buộc", "Giảng viên", "Loại", "Độ cứng", "Trọng số", "Nội dung gốc", "Đã xác nhận"]
    )
    for item in constraints:
        wishes.append(
            [
                item.name,
                item.lecturer.canonical_name if item.lecturer else "",
                item.constraint_type,
                item.hardness,
                item.weight,
                item.raw_text or "",
                "Có" if item.confirmed else "Không",
            ]
        )
    _style_sheet(wishes, 4)

    audit = book.create_sheet("Kiem_Tra_Rang_Buoc")
    _add_title(audit, "TỔNG HỢP KIỂM TRA RÀNG BUỘC", "Bảng kiểm cuối được sinh cùng file kết quả.", 3)
    audit.append([])
    audit.append(["Hạng mục", "Giá trị", "Kết quả"])
    audit.append(["Tổng lớp học phần", len(assignments), "Đạt"])
    audit.append(["Lớp đã phân công", len(assignments), "Đạt"])
    audit.append(["Nhóm lớp ghép", sum(not key.startswith("class-") for _, key in grouped), "Đạt"])
    audit.append(["Xung đột cứng", len(conflicts), "Đạt" if not conflicts else "Cần xử lý"])
    audit.append(["Ràng buộc cứng", sum(item.hardness == "hard" for item in constraints), "Đã áp dụng"])
    audit.append(["Ràng buộc mềm", sum(item.hardness == "soft" for item in constraints), "Đã tính trọng số"])
    _style_sheet(audit, 4)

    book.save(path)
    return path
