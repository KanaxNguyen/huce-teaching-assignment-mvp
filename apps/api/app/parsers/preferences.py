from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

from app.parsers.schedule import clean_text

CONSTRAINT_TYPES = {
    "UNAVAILABLE", "AVOID_PERIOD", "PREFERRED_PERIOD", "PREFER_CONSECUTIVE_PERIODS",
    "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK",
    "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "RAW_NOTE",
    "SEMINAR_COMMITMENT", "SEMINAR_NOTE",
}
DAY_SCOPES = {"T2", "T3", "T4", "T5", "T6", "T7", "CN", "ALL_WEEKDAYS", "ALL_DAYS"}
HARDNESS_VALUES = {"SOFT", "HARD"}
STATUS_VALUES = {"DRAFT", "CONFIRMED", "NEEDS_REVIEW", "REJECTED"}
V2_PREFERENCE_HEADERS = [
    "Mã GV*", "Họ tên GV", "Ngữ cảnh*", "Loại ràng buộc*", "Thứ/Phạm vi*", "Tiết bắt đầu",
    "Tiết kết thúc", "Ngày bắt đầu", "Ngày kết thúc", "Độ cứng*", "Trọng số",
    "Giá trị số", "Ghi chú / Nguyên văn", "Trạng thái",
]


@dataclass
class ParsedPreference:
    lecturer_alias: str
    canonical_name: str
    weekday: int | None
    constraint_type: str
    target: dict
    raw_text: str
    confidence: float
    source_row: int
    lecturer_code: str | None = None
    source_sheet: str = ""
    source_cell: str = ""
    day_scope: str | None = None
    start_period: int | None = None
    end_period: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    hardness: str = "soft"
    weight: float = 0.8
    numeric_value: float | None = None
    confidence_label: str = "LOW"
    needs_review: bool = True
    review_reason: str | None = None
    status: str = "NEEDS_REVIEW"
    context_type: str = "TEACHING"
    context_confidence: str = "HIGH"
    context_confirmed: bool = False
    seminar_link: str | None = None


@dataclass
class ParsedSharedSeminar:
    seminar_code: str
    name: str
    participant_codes: list[str]
    day_scopes: list[str]
    period_blocks: list[list[int]]
    hardness: str
    weight: float
    raw_text: str
    source_sheet: str
    source_row: int
    source_cell: str
    status: str
    needs_review: bool = False
    review_reason: str | None = None


@dataclass
class PreferenceParseResult:
    format: str
    drafts: list[ParsedPreference] = field(default_factory=list)
    seminars: list[ParsedSharedSeminar] = field(default_factory=list)
    invalid_rows: int = 0
    raw_clauses: int = 0
    dropped_clauses: int = 0


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").replace("đ", "d")


def _normalized_header(value: object) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip().casefold()


def _periods_from_text(text: str) -> list[int]:
    """Extract complete inclusive period ranges without treating weekdays as periods."""
    plain = _plain(text)
    periods: list[int] = []
    compact = re.search(r"(?:tiet|ca|block)\s*([1-9]{2,3})(?!\d)", plain)
    if compact and compact.group(1) in {"123", "456", "789"}:
        periods.extend(int(value) for value in compact.group(1))
    for start_text, end_text in re.findall(
        r"(?:tiet|ca|block)?\s*(\d{1,2})\s*(?:-|–|den|toi)\s*(\d{1,2})", plain
    ):
        start, end = int(start_text), int(end_text)
        if 1 <= start <= end <= 15:
            periods.extend(range(start, end + 1))
    if periods:
        return sorted(set(periods))
    match = re.search(r"(?:tiet|ca|block)\s*(\d{1,2})(?!\s*(?:-|–|den|toi))", plain)
    if match and 1 <= int(match.group(1)) <= 15:
        return [int(match.group(1))]
    return []


def _weekday_from_text(text: str) -> int | None:
    plain = _plain(text)
    if re.search(r"chu\s*nhat|\bcn\b", plain):
        return 8
    match = re.search(r"(?:thu|\bt)\s*([2-7])", plain)
    return int(match.group(1)) if match else None


def _day_scope(weekday: int | None, text: str = "") -> str | None:
    plain = _plain(text)
    if any(token in plain for token in ("trong tuan", "cac buoi", "cac ngay", "t2 den t6")):
        return "ALL_WEEKDAYS"
    if "tat ca" in plain or "moi ngay" in plain:
        return "ALL_DAYS"
    return "CN" if weekday == 8 else (f"T{weekday}" if weekday else None)


def _periods_for_part_of_day(text: str) -> list[int]:
    plain = _plain(text)
    if "3 tiet cuoi sang" in plain:
        return [4, 5, 6]
    if "3 tiet dau chieu" in plain:
        return [7, 8, 9]
    explicit = _periods_from_text(text)
    if explicit:
        return explicit
    if "ca ngay" in plain:
        return list(range(1, 13))
    if "sang" in plain:
        return list(range(1, 7))
    if "chieu" in plain:
        return list(range(7, 13))
    if "toi" in plain:
        return list(range(10, 13))
    return []


def _target(day_scope: str | None, periods: list[int], numeric_value: float | None = None) -> dict:
    target: dict = {"day_scope": day_scope, "periods": periods}
    if day_scope in {"T2", "T3", "T4", "T5", "T6", "T7"}:
        target["weekday"] = int(day_scope[1:])
    elif day_scope == "CN":
        target["weekday"] = 8
    elif day_scope in {"ALL_WEEKDAYS", "ALL_DAYS"}:
        weekdays = range(2, 7) if day_scope == "ALL_WEEKDAYS" else range(2, 9)
        target["slots"] = [{"weekday": weekday, "periods": periods} for weekday in weekdays]
    if numeric_value is not None:
        target["value"] = numeric_value
        target["max"] = numeric_value
    return target


def describe_preference(constraint_type: str, target: dict) -> str:
    normalized = constraint_type.upper()
    normalized = {"PREFER_PERIOD": "PREFERRED_PERIOD", "AVOID": "AVOID_PERIOD", "RAW_PREFERENCE": "RAW_NOTE"}.get(normalized, normalized)
    labels = {
        "UNAVAILABLE": "Không xếp lịch", "AVOID_PERIOD": "Ưu tiên tránh",
        "PREFERRED_PERIOD": "Ưu tiên xếp lịch", "PREFER_CONSECUTIVE_PERIODS": "Ưu tiên dạy liền",
        "MIN_CLASSES": "Số lớp tối thiểu", "MAX_CLASSES": "Số lớp tối đa",
        "MAX_SESSIONS_PER_DAY": "Số buổi tối đa mỗi ngày", "MAX_DAYS_PER_WEEK": "Số ngày tối đa mỗi tuần",
        "MIN_FREE_MORNING_PER_WEEK": "Số buổi sáng nghỉ tối thiểu", "REQUIRED_ASSIGNMENT": "Bắt buộc phân công",
        "FORBIDDEN_ASSIGNMENT": "Không được phân công", "RAW_NOTE": "Cần trưởng bộ môn diễn giải",
        "AVAILABLE": "Có thể xếp lịch", "SEMINAR": "Giữ lịch seminar",
    }
    slots = target.get("slots") or []
    if slots:
        rendered = []
        for slot in slots:
            weekday = slot.get("weekday")
            periods = slot.get("periods") or []
            day = "Chủ Nhật" if weekday == 8 else f"Thứ {weekday}"
            rendered.append(f"{day}{f', tiết {min(periods)}–{max(periods)}' if periods else ''}")
        return f"{labels.get(normalized, 'Ràng buộc')} · {'; '.join(rendered)}"
    scope = target.get("day_scope")
    weekday = target.get("weekday")
    day = {"ALL_WEEKDAYS": "Thứ 2–Thứ 6", "ALL_DAYS": "mọi ngày", "CN": "Chủ Nhật"}.get(
        scope, "Chủ Nhật" if weekday == 8 else (f"Thứ {weekday}" if weekday else "mọi ngày")
    )
    periods = target.get("periods") or target.get("period_range") or []
    suffix = f", tiết {min(periods)}–{max(periods)}" if periods else ""
    return f"{labels.get(normalized, 'Ràng buộc')} · {day}{suffix}"


def _legacy_rule(text: str, column_weekday: int | None) -> tuple[str, dict, str, str | None]:
    plain = _plain(text)
    explicit_day = _weekday_from_text(text)
    generic_part_of_day = explicit_day is None and any(token in plain for token in ("sang", "chieu", "toi"))
    day = _day_scope(explicit_day or (None if generic_part_of_day else column_weekday), text)
    if generic_part_of_day:
        day = "ALL_WEEKDAYS"
    periods = _periods_for_part_of_day(text)
    rule_day = day or "ALL_WEEKDAYS"
    if "nghi it nhat" in plain and "buoi sang" in plain:
        match = re.search(r"(?:it nhat(?: la)?|toi thieu)\s*0?(\d+)", plain)
        value = float(match.group(1)) if match else 1.0
        return "MIN_FREE_MORNING_PER_WEEK", _target("ALL_WEEKDAYS", list(range(1, 7)), value), "HIGH", None
    consecutive = re.search(r"(?:lien|lien tuc)\s*0?(\d+)\s*tiet", plain)
    if consecutive:
        value = float(consecutive.group(1))
        return "PREFER_CONSECUTIVE_PERIODS", _target(rule_day, [], value), "HIGH", None
    if any(token in plain for token in ("xin nghi", "nghi day", "khong day", "khong the day", "khong xep")):
        if periods or explicit_day or "cac buoi" in plain:
            return "UNAVAILABLE", _target(rule_day, periods), "HIGH", None
    if "tranh" in plain and periods:
        return "AVOID_PERIOD", _target(rule_day, periods), "HIGH", None
    if "3 tiet cuoi sang" in plain or "3 tiet dau chieu" in plain:
        return "RAW_NOTE", _target("ALL_WEEKDAYS", periods), "MEDIUM", "Khung '3 tiết cuối sáng/đầu chiều' cần xác nhận theo quy ước tiết của bộ môn."
    if any(token in plain for token in ("dang ki day", "dang ky day", "dk day", "xin day", "duoc day", "day cac", "co the")) or re.search(r"\bday\b", plain):
        if periods or any(token in plain for token in ("sang", "chieu", "toi")):
            return "PREFERRED_PERIOD", _target(rule_day, periods), "HIGH", None
    if any(token in plain for token in ("gon", "it ngay")):
        return "RAW_NOTE", _target(day, periods), "MEDIUM", "Chưa đủ cấu trúc để suy ra một quy tắc solver duy nhất."
    return "RAW_NOTE", _target(day, periods), "LOW", "Không nhận diện chắc chắn; cần trưởng bộ môn diễn giải."


def _infer(text: str, weekday: int | None) -> tuple[str, dict, float]:
    """Compatibility wrapper used by older callers and tests."""
    kind, target, confidence, _ = _legacy_rule(text, weekday)
    legacy_kind = {
        "UNAVAILABLE": "unavailable", "AVOID_PERIOD": "avoid", "PREFERRED_PERIOD": "prefer_period",
        "RAW_NOTE": "raw_preference", "PREFER_CONSECUTIVE_PERIODS": "compact_schedule",
    }.get(kind, kind)
    return legacy_kind, target, {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.35}[confidence]


def _as_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"Ngày không hợp lệ: {text}")


def _as_number(value: object, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    number = float(value)
    return int(number) if number.is_integer() else number


def _split_legacy_clauses(text: str) -> list[str]:
    chunks = re.split(
        r"(?:\r?\n)+|(?<=[.!?])\s+|,\s*(?=(?:xin|em xin|cô |co |thầy |thay |seminar|có thể|co the)\b)|\s+[Vv]à\s+(?=xin\b)",
        text.strip(), flags=re.IGNORECASE,
    )
    return [chunk.strip(" ,.;") for chunk in chunks if chunk.strip(" ,.;")]


def detect_preference_format(path: Path) -> str:
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in book.worksheets:
        headers = [_normalized_header(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        if sheet.title == "Nguyen_vong_GV" and all(_normalized_header(value) in headers for value in V2_PREFERENCE_HEADERS):
            return "STRUCTURED_V2"
    return "LEGACY"


def _invalid_structured_draft(sheet, row: int, values: list[object], reason: str) -> ParsedPreference:
    raw = clean_text(values[12] if len(values) > 12 else "") or " | ".join(clean_text(value) for value in values if value)
    return ParsedPreference(
        clean_text(values[1] if len(values) > 1 else ""), clean_text(values[1] if len(values) > 1 else ""),
        None, "RAW_NOTE", {}, raw, 0.0, row, lecturer_code=clean_text(values[0]) or None,
        source_sheet=sheet.title, source_cell=f"A{row}:N{row}", confidence_label="LOW",
        needs_review=True, review_reason=reason, status="NEEDS_REVIEW",
    )


def _parse_structured(book) -> PreferenceParseResult:
    result = PreferenceParseResult(format="STRUCTURED_V2")
    sheet = book["Nguyen_vong_GV"]
    for row in range(2, sheet.max_row + 1):
        values = [sheet.cell(row, column).value for column in range(1, 15)]
        if not any(value not in (None, "") for value in values):
            continue
        result.raw_clauses += 1
        try:
            code, name, context, kind, scope = (clean_text(values[index]) for index in range(5))
            context = context.upper()
            hardness = clean_text(values[9]).upper()
            status = (clean_text(values[13]) or "DRAFT").upper()
            if not code:
                raise ValueError("Thiếu Mã GV; cần resolve identity trước khi xác nhận.")
            if kind.upper() not in CONSTRAINT_TYPES:
                raise ValueError(f"Loại ràng buộc không hợp lệ: {kind}")
            if context not in {"TEACHING", "SEMINAR", "MIXED"}:
                raise ValueError(f"Ngữ cảnh không hợp lệ: {context}")
            if scope.upper() not in DAY_SCOPES:
                raise ValueError(f"Thứ/Phạm vi không hợp lệ: {scope}")
            if hardness not in {"SOFT", "HARD"}:
                raise ValueError(f"Độ cứng không hợp lệ: {hardness}")
            if status not in {"DRAFT", "CONFIRMED", "NEEDS_REVIEW", "REJECTED"}:
                raise ValueError(f"Trạng thái không hợp lệ: {status}")
            start = int(values[5]) if values[5] not in (None, "") else None
            end = int(values[6]) if values[6] not in (None, "") else None
            if (start is None) != (end is None) or (start is not None and not 1 <= start <= end <= 15):
                raise ValueError("Khoảng tiết phải có đủ bắt đầu/kết thúc và nằm trong 1–15.")
            periods = list(range(start, end + 1)) if start is not None and end is not None else []
            weight = _as_number(values[10], default=0.8)
            if weight is None or not 0 <= weight <= 1:
                raise ValueError("Trọng số phải nằm trong 0–1.")
            numeric = _as_number(values[11])
            start_date, end_date = _as_date(values[7]), _as_date(values[8])
            if start_date and end_date and end_date < start_date:
                raise ValueError("Ngày kết thúc phải không trước ngày bắt đầu.")
            raw = clean_text(values[12])
            unsupported = kind.upper() in {"PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK"}
            incomplete_assignment = kind.upper() in {"REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT"}
            seminar_types = {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}
            incompatible_context = (
                (context == "TEACHING" and kind.upper() in seminar_types)
                or (context == "SEMINAR" and kind.upper() not in seminar_types)
            )
            needs_review = (
                status == "NEEDS_REVIEW"
                or kind.upper() in {"RAW_NOTE", "SEMINAR_NOTE"}
                or context == "MIXED"
                or unsupported
                or incomplete_assignment
                or incompatible_context
            )
            if context == "SEMINAR" and kind.upper() == "SEMINAR_COMMITMENT" and (not periods or not scope):
                needs_review = True
            parsed_target = _target(scope.upper(), periods, numeric)
            if kind.upper() == "MIN_CLASSES" and numeric is not None:
                parsed_target.pop("max", None); parsed_target["min"] = numeric
            if start_date: parsed_target["start_date"] = start_date.isoformat()
            if end_date: parsed_target["end_date"] = end_date.isoformat()
            result.drafts.append(ParsedPreference(
                lecturer_alias=name or code, canonical_name=name or code, weekday=None,
                constraint_type=kind.upper(), target=parsed_target, raw_text=raw,
                confidence=1.0, source_row=row, lecturer_code=code, source_sheet=sheet.title,
                source_cell=f"A{row}:N{row}", day_scope=scope.upper(), start_period=start, end_period=end,
                start_date=start_date, end_date=end_date, hardness=hardness.lower(), weight=weight,
                numeric_value=numeric, confidence_label="HIGH", needs_review=needs_review,
                review_reason=("MIXED phải tách thành các rule nguyên tử trước khi Apply." if context == "MIXED" else
                               "Loại rule chưa phù hợp ngữ cảnh đã chọn." if incompatible_context else
                               "Rule đã được bảo toàn nhưng solver hiện chưa có semantics tương ứng." if unsupported else
                               "Cần chọn TeachingGroup cụ thể trước khi Apply." if incomplete_assignment else
                               "Ghi chú chưa có scheduling semantics cụ thể." if kind.upper() in {"RAW_NOTE", "SEMINAR_NOTE"} else
                               "Thiếu ngày hoặc tiết seminar." if needs_review else None),
                status="NEEDS_REVIEW" if needs_review else status, context_type=context,
                context_confidence="HIGH",
            ))
        except (TypeError, ValueError) as error:
            result.invalid_rows += 1
            result.drafts.append(_invalid_structured_draft(sheet, row, values, str(error)))
    if "Seminar_Shared" in book.sheetnames:
        seminar_sheet = book["Seminar_Shared"]
        for row in range(2, seminar_sheet.max_row + 1):
            values = [seminar_sheet.cell(row, column).value for column in range(1, 10)]
            if not any(value not in (None, "") for value in values):
                continue
            result.raw_clauses += 1
            try:
                code, name = clean_text(values[0]), clean_text(values[1])
                participants = [item.strip() for item in clean_text(values[2]).split(";") if item.strip()]
                days = [item.strip().upper() for item in clean_text(values[3]).split(";") if item.strip()]
                blocks = []
                for block in clean_text(values[4]).split(";"):
                    periods = _periods_from_text(f"tiết {block.strip()}")
                    if not periods:
                        raise ValueError(f"Khung tiết không hợp lệ: {block}")
                    blocks.append(periods)
                hardness = clean_text(values[5]).upper()
                weight = _as_number(values[6], default=0.8)
                status = (clean_text(values[8]) or "DRAFT").upper()
                if not code or not name or not participants:
                    raise ValueError("Thiếu mã, tên hoặc người tham gia seminar.")
                if not days or any(day not in DAY_SCOPES for day in days):
                    raise ValueError("Thứ cho phép của seminar không hợp lệ.")
                if hardness not in {"SOFT", "HARD"} or status not in {"DRAFT", "CONFIRMED", "NEEDS_REVIEW", "REJECTED"} or weight is None or not 0 <= weight <= 1:
                    raise ValueError("Hardness, weight hoặc status seminar không hợp lệ.")
                result.seminars.append(ParsedSharedSeminar(
                    code, name, participants, days, blocks, hardness.lower(), weight, clean_text(values[7]),
                    seminar_sheet.title, row, f"A{row}:I{row}", status,
                    needs_review=status == "NEEDS_REVIEW",
                ))
            except (TypeError, ValueError) as error:
                result.invalid_rows += 1
                result.seminars.append(ParsedSharedSeminar(
                    clean_text(values[0]), clean_text(values[1]) or "Seminar cần rà soát", [], [], [], "soft", 0.8,
                    clean_text(values[7]), seminar_sheet.title, row, f"A{row}:I{row}", "NEEDS_REVIEW", True, str(error),
                ))
    return result


def _parse_legacy(book) -> PreferenceParseResult:
    sheet = book[book.sheetnames[0]]
    result = PreferenceParseResult(format="LEGACY")
    for row in range(4, min(sheet.max_row, 1000) + 1):
        alias = clean_text(sheet.cell(row, 2).value)
        if not alias:
            continue
        for column in range(3, 11):
            raw_cell = clean_text(sheet.cell(row, column).value)
            if not raw_cell:
                continue
            clauses = _split_legacy_clauses(raw_cell)
            result.raw_clauses += len(clauses)
            for clause_index, clause in enumerate(clauses, start=1):
                weekday = column - 1 if column <= 9 else None
                if column == 3 and _weekday_from_text(clause) is None:
                    weekday = None
                clause_plain = _plain(clause)
                segmented_teaching = re.search(
                    r"(?i)(?:sáng|chiều|tối|sang|chieu|toi)\s*:\s*(?:(?:có thể|co the|xin|muốn|muon)\s+)?dạy\b",
                    clause,
                )
                if "seminar" in clause_plain and segmented_teaching:
                    seminar_text = clause[:segmented_teaching.start()].strip()
                    teaching_text = clause[segmented_teaching.start():].strip()
                    seminar_day = _day_scope(_weekday_from_text(seminar_text) or weekday, seminar_text)
                    seminar_periods = _periods_for_part_of_day(seminar_text)
                    seminar_complete = bool(seminar_day and seminar_periods)
                    seminar_target = _target(seminar_day, seminar_periods)
                    teaching_kind, teaching_target, teaching_confidence, teaching_reason = _legacy_rule(teaching_text, weekday)
                    teaching_periods = teaching_target.get("periods") or []
                    teaching_review = teaching_confidence == "LOW" or teaching_kind in {
                        "RAW_NOTE", "PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK",
                    }
                    common = dict(
                        lecturer_alias=alias, canonical_name=alias, raw_text=clause,
                        source_row=row, source_sheet=sheet.title, context_confidence="HIGH",
                    )
                    result.drafts.append(ParsedPreference(
                        weekday=seminar_target.get("weekday"),
                        constraint_type="SEMINAR_COMMITMENT" if seminar_complete else "SEMINAR_NOTE",
                        target=seminar_target, confidence=0.9 if seminar_complete else 0.35,
                        source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}A",
                        day_scope=seminar_day,
                        start_period=min(seminar_periods) if seminar_periods else None,
                        end_period=max(seminar_periods) if seminar_periods else None,
                        confidence_label="HIGH" if seminar_complete else "LOW",
                        needs_review=not seminar_complete,
                        review_reason=None if seminar_complete else "Thiếu ngày hoặc tiết seminar; không tự suy đoán.",
                        status="DRAFT" if seminar_complete else "NEEDS_REVIEW",
                        context_type="SEMINAR", **common,
                    ))
                    result.drafts.append(ParsedPreference(
                        weekday=teaching_target.get("weekday"), constraint_type=teaching_kind,
                        target=teaching_target,
                        confidence={"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.35}[teaching_confidence],
                        source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}B",
                        day_scope=teaching_target.get("day_scope"),
                        start_period=min(teaching_periods) if teaching_periods else None,
                        end_period=max(teaching_periods) if teaching_periods else None,
                        numeric_value=teaching_target.get("value"), confidence_label=teaching_confidence,
                        needs_review=teaching_review, review_reason=teaching_reason,
                        status="NEEDS_REVIEW" if teaching_review else "DRAFT",
                        context_type="TEACHING", **common,
                    ))
                    continue
                is_mixed = "seminar" in clause_plain and any(token in clause_plain for token in (" vi ", " nen ")) and any(token in clause_plain for token in ("day", "gon"))
                if is_mixed:
                    before, after = re.split(r"\b(?:vi|nen)\b", clause_plain, maxsplit=1)
                    seminar_days = sorted({int(value) for value in re.findall(r"[2-7]", before)})
                    teaching_days = sorted({int(value) for value in re.findall(r"[2-7]", after)})
                    common = dict(
                        lecturer_alias=alias, canonical_name=alias, weekday=None, raw_text=clause,
                        confidence=0.7, source_row=row, source_sheet=sheet.title,
                        confidence_label="MEDIUM", needs_review=True, status="NEEDS_REVIEW",
                        context_confidence="HIGH",
                    )
                    result.drafts.append(ParsedPreference(
                        constraint_type="SEMINAR_NOTE", target={"weekdays": seminar_days, "periods": []},
                        source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}A",
                        review_reason="Đã tách phần seminar nhưng chưa có khung tiết cụ thể.",
                        context_type="SEMINAR", **common,
                    ))
                    result.drafts.append(ParsedPreference(
                        constraint_type="RAW_NOTE", target={"weekdays": teaching_days, "periods": []},
                        source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}B",
                        review_reason="Đã tách phần lịch dạy; cần chọn scheduling semantics cụ thể.",
                        context_type="TEACHING", **common,
                    ))
                    continue
                is_seminar_event = "seminar" in clause_plain and not any(token in clause_plain for token in ("xin nghi", "nghi day", "khong day"))
                if is_seminar_event:
                    seminar_day = _day_scope(_weekday_from_text(clause) or weekday, clause)
                    seminar_periods = _periods_for_part_of_day(clause)
                    complete = bool(seminar_day and seminar_periods)
                    target = _target(seminar_day, seminar_periods)
                    result.drafts.append(ParsedPreference(
                        alias, alias, target.get("weekday"), "SEMINAR_COMMITMENT" if complete else "SEMINAR_NOTE",
                        target, clause, 0.9 if complete else 0.35, row, source_sheet=sheet.title,
                        source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}", day_scope=seminar_day,
                        start_period=min(seminar_periods) if seminar_periods else None,
                        end_period=max(seminar_periods) if seminar_periods else None,
                        confidence_label="HIGH" if complete else "LOW", needs_review=not complete,
                        review_reason=None if complete else "Thiếu ngày hoặc tiết seminar; không tự suy đoán.",
                        status="DRAFT" if complete else "NEEDS_REVIEW", context_type="SEMINAR",
                        context_confidence="HIGH",
                    ))
                    continue
                kind, target, confidence, reason = _legacy_rule(clause, weekday)
                if any(token in _plain(clause) for token in ("trong tuan", "cac buoi", "cac ngay")):
                    target["day_scope"] = "ALL_WEEKDAYS"
                    target.pop("weekday", None)
                numeric = target.get("value")
                confidence_value = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.35}[confidence]
                needs_review = confidence == "LOW" or kind in {"RAW_NOTE", "PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK"}
                if kind in {"PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK"}:
                    reason = "Rule đã được bảo toàn nhưng solver hiện chưa có semantics tương ứng."
                periods = target.get("periods") or []
                result.drafts.append(ParsedPreference(
                    alias, alias, target.get("weekday"), kind, target, clause, confidence_value, row,
                    source_sheet=sheet.title, source_cell=f"{sheet.cell(row, column).coordinate}#{clause_index}",
                    day_scope=target.get("day_scope"), start_period=min(periods) if periods else None,
                    end_period=max(periods) if periods else None, numeric_value=numeric,
                    confidence_label=confidence, needs_review=needs_review, review_reason=reason,
                    status="NEEDS_REVIEW" if needs_review else "DRAFT", context_type="TEACHING",
                    context_confidence="HIGH",
                ))
    # A mixed source clause intentionally expands to multiple atomic drafts;
    # every non-empty source clause reaches at least one draft.
    result.dropped_clauses = 0
    return result


def parse_preference_workbook(path: Path) -> PreferenceParseResult:
    book = openpyxl.load_workbook(path, read_only=False, data_only=True)
    return _parse_structured(book) if detect_preference_format(path) == "STRUCTURED_V2" else _parse_legacy(book)


def parse_preferences(path: Path) -> list[ParsedPreference]:
    """Backward-compatible list API; new callers should use parse_preference_workbook."""
    return parse_preference_workbook(path).drafts
