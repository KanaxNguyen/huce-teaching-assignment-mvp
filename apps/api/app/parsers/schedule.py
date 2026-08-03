from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
import xlrd


@dataclass
class ParsedSession:
    weekday: int
    start_period: int
    end_period: int
    room: str
    start_date: date | None
    end_date: date | None
    raw_weeks: str
    active_weeks: list[int]
    source_row: int

    def signature(self) -> tuple:
        return (
            self.weekday,
            self.start_period,
            self.end_period,
            self.room.casefold(),
            self.start_date.isoformat() if self.start_date else "",
            self.end_date.isoformat() if self.end_date else "",
            tuple(self.active_weeks),
        )


@dataclass
class ParsedClass:
    course_code: str
    course_name: str
    class_code: str
    credits: float
    lecturer_code: str | None
    lecturer_name: str | None
    locked_assignment: bool
    source_file: str
    source_sheet: str
    source_row: int
    raw_values: dict[str, Any]
    sessions: list[ParsedSession] = field(default_factory=list)
    merged_group_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.course_code}::{self.class_code}"


@dataclass
class MergedGroup:
    id: str
    class_keys: list[str]


@dataclass
class ParseIssue:
    severity: str
    code: str
    message: str
    source_file: str
    source_sheet: str
    source_row: int | None = None
    field: str | None = None
    raw_value: str | None = None
    suggestion: str | None = None


@dataclass
class ScheduleParseResult:
    classes: list[ParsedClass]
    merged_groups: list[MergedGroup]
    issues: list[ParseIssue]
    rows_accepted: int
    rows_rejected: int
    header_row: int


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def clean_code(value: Any) -> str:
    text = clean_text(value)
    return text[:-2] if re.fullmatch(r"\d+\.0", text) else text


def parse_lecturer(value: Any) -> tuple[str | None, str | None]:
    text = clean_text(value)
    if not text:
        return None, None
    match = re.match(r"^\[([^\]]+)]\s*(.+)$", text)
    if match:
        return clean_code(match.group(1)), clean_text(match.group(2))
    return None, re.sub(r"^(thầy|cô)\s+", "", text, flags=re.IGNORECASE)


def parse_periods(value: Any) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", clean_text(value))]
    if not numbers:
        raise ValueError("Không có tiết học")
    start, end = numbers[0], numbers[-1]
    if start < 1 or end < start or end > 15:
        raise ValueError("Khoảng tiết không hợp lệ")
    return start, end


def parse_weekday(value: Any) -> int:
    text = clean_text(value).casefold()
    if text in {"cn", "chủ nhật", "chu nhat"}:
        return 8
    numbers = re.findall(r"\d+", text)
    if not numbers or not 2 <= int(numbers[0]) <= 8:
        raise ValueError("Thứ phải nằm trong 2–8")
    return int(numbers[0])


def decode_weeks(value: Any) -> tuple[str, list[int]]:
    raw = "" if value is None else unicodedata.normalize("NFC", str(value))
    raw = raw.replace("\r", "").replace("\n", "")
    if not raw:
        raise ValueError("Thiếu tuần học")
    invalid = [char for char in raw if not (char.isspace() or char.isdigit())]
    if invalid:
        raise ValueError(f"Ký tự tuần học không hợp lệ: {''.join(sorted(set(invalid)))}")
    active = [index + 1 for index, char in enumerate(raw) if char.isdigit()]
    if not active:
        raise ValueError("Không giải mã được tuần học")
    return raw, active


def parse_date(value: Any, datemode: int = 0) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return xlrd.xldate_as_datetime(value, datemode).date()
    text = clean_text(value)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Ngày không hợp lệ: {text}")


def _read_rows(path: Path) -> tuple[str, list[list[Any]], int]:
    if path.suffix.lower() == ".xls":
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_index(0)
        return sheet.name, [sheet.row_values(row)[:14] for row in range(sheet.nrows)], book.datemode
    book = openpyxl.load_workbook(path, read_only=False, data_only=True)
    sheet = book[book.sheetnames[0]]
    rows = [
        [sheet.cell(row, col).value for col in range(1, 15)] for row in range(1, min(sheet.max_row, 5000) + 1)
    ]
    return sheet.title, rows, 0


def _find_header(rows: list[list[Any]]) -> int:
    required = {"stt", "tên môn học"}
    for index, row in enumerate(rows[:40]):
        values = {clean_text(value).casefold() for value in row}
        has_code = "mã học phần" in values or "mã hp" in values
        has_class = "mã lớp học" in values
        if required.issubset(values) and has_code and has_class:
            return index
    raise ValueError("Không tìm thấy dòng tiêu đề lịch học")


def parse_schedule(path: Path) -> ScheduleParseResult:
    sheet_name, rows, datemode = _read_rows(path)
    header = _find_header(rows)
    issues: list[ParseIssue] = []
    grouped: dict[str, ParsedClass] = {}
    rejected = 0
    accepted = 0

    for index, row in enumerate(rows[header + 2 :], start=header + 3):
        padded = (row + [None] * 14)[:14]
        stt, course_code, course_name, class_code = padded[:4]
        if not clean_text(stt) and not any(clean_text(v) for v in padded[:4]):
            continue
        if not clean_code(course_code) or not clean_text(course_name) or not clean_code(class_code):
            if any(clean_text(v) for v in padded[:4]):
                rejected += 1
                issues.append(
                    ParseIssue(
                        "error",
                        "missing_required_field",
                        "Dòng không có đủ mã học phần, tên môn và mã lớp.",
                        path.name,
                        sheet_name,
                        index,
                        suggestion="Bổ sung trường bắt buộc hoặc loại dòng chữ ký.",
                    )
                )
            continue
        try:
            weekday = parse_weekday(padded[5])
            start_period, end_period = parse_periods(padded[6])
            start_date = parse_date(padded[10], datemode)
            end_date = parse_date(padded[11], datemode)
            raw_weeks, active_weeks = decode_weeks(padded[12])
            if start_date and end_date and end_date < start_date:
                raise ValueError("Ngày kết thúc trước ngày bắt đầu")
        except ValueError as error:
            rejected += 1
            issues.append(
                ParseIssue(
                    "error",
                    "invalid_schedule_value",
                    str(error),
                    path.name,
                    sheet_name,
                    index,
                    raw_value=str(padded[5:13]),
                    suggestion="Sửa dữ liệu nguồn rồi upload lại; hệ thống không tự đoán.",
                )
            )
            continue

        code = clean_code(course_code)
        class_id = clean_code(class_code)
        key = f"{code}::{class_id}"
        lecturer_code, lecturer_name = parse_lecturer(padded[13])
        credits_text = clean_text(padded[8])
        try:
            credits = float(credits_text) if credits_text else 0
        except ValueError:
            credits = 0
        parsed_session = ParsedSession(
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            room=clean_text(padded[7]),
            start_date=start_date,
            end_date=end_date,
            raw_weeks=raw_weeks,
            active_weeks=active_weeks,
            source_row=index,
        )
        if key not in grouped:
            grouped[key] = ParsedClass(
                course_code=code,
                course_name=clean_text(course_name),
                class_code=class_id,
                credits=credits,
                lecturer_code=lecturer_code,
                lecturer_name=lecturer_name,
                locked_assignment=bool(lecturer_name),
                source_file=path.name,
                source_sheet=sheet_name,
                source_row=index,
                raw_values={"row": [str(v) if v is not None else "" for v in padded]},
            )
        else:
            current = grouped[key]
            if (
                lecturer_name
                and current.lecturer_name
                and lecturer_name.casefold() != current.lecturer_name.casefold()
            ):
                issues.append(
                    ParseIssue(
                        "error",
                        "multiple_lecturers_for_class",
                        f"Lớp {class_id} có nhiều giảng viên khác nhau.",
                        path.name,
                        sheet_name,
                        index,
                        "Giảng viên",
                        lecturer_name,
                        "Xác nhận một giảng viên áp dụng cho toàn bộ buổi.",
                    )
                )
            elif lecturer_name and not current.lecturer_name:
                current.lecturer_code = lecturer_code
                current.lecturer_name = lecturer_name
                current.locked_assignment = True
        grouped[key].sessions.append(parsed_session)
        accepted += 1

    classes = list(grouped.values())
    pair_candidates = []
    for left_index, left in enumerate(classes):
        for right_index in range(left_index + 1, len(classes)):
            right = classes[right_index]
            if left.course_code != right.course_code:
                continue
            shared_sessions = sum(
                sessions_overlap(left_session, right_session)
                and bool(_room_tokens(left_session.room).intersection(_room_tokens(right_session.room)))
                for left_session in left.sessions
                for right_session in right.sessions
            )
            if shared_sessions:
                pair_candidates.append(
                    (-shared_sessions, left.class_code, right.class_code, left_index, right_index)
                )

    merged_groups = []
    used_indexes = set()
    for _, _, _, left_index, right_index in sorted(pair_candidates):
        if left_index in used_indexes or right_index in used_indexes:
            continue
        group_id = f"MG-{len(merged_groups) + 1:03d}"
        candidates = [classes[left_index], classes[right_index]]
        used_indexes.update((left_index, right_index))
        for item in candidates:
            item.merged_group_id = group_id
        merged_groups.append(MergedGroup(group_id, sorted(item.key for item in candidates)))

    return ScheduleParseResult(
        classes=classes,
        merged_groups=merged_groups,
        issues=issues,
        rows_accepted=accepted,
        rows_rejected=rejected,
        header_row=header + 1,
    )


def sessions_overlap(left: ParsedSession, right: ParsedSession) -> bool:
    if left.weekday != right.weekday:
        return False
    if left.end_period < right.start_period or right.end_period < left.start_period:
        return False
    if not set(left.active_weeks).intersection(right.active_weeks):
        return False
    if left.start_date and right.end_date and left.start_date > right.end_date:
        return False
    if right.start_date and left.end_date and right.start_date > left.end_date:
        return False
    return True


def _room_tokens(value: str) -> set[str]:
    return {item.strip().casefold() for item in value.split(",") if item.strip()}
