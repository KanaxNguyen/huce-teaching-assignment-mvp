from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from app.parsers.schedule import clean_text

ALIASES = {
    "thoan": "Phạm Đức Thoan",
    "bằng giang": "Nguyễn Bằng Giang",
    "giang": "Nguyễn Bằng Giang",
    "cường": "Lê Viết Cường",
    "hùng": "Ngô Quang Hùng",
    "hằng": "Trịnh Thị Minh Hằng",
    "hương giang": "Vũ Thị Hương Giang",
    "khiên": "Trần Văn Khiên",
    "nam": "Nguyễn Hải Nam",
    "nguyệt": "Nguyễn Minh Nguyệt",
    "ngân": "Vũ Thị Ngân",
    "thuỷ": "Vũ Thị Thủy",
    "thủy": "Vũ Thị Thủy",
    "trình": "Bùi Khánh Trình",
    "tuyên": "Nguyễn Đặng Tuyên",
    "tuyết": "Lương Thị Tuyết",
    "x linh": "Nguyễn Xuân Linh",
    "kiều linh": "Kiều Thị Thùy Linh",
    "klinh": "Kiều Thị Thùy Linh",
    "mai hồng": "Mai Thị Hồng",
    "liễu": "Trần Thị Liễu",
    "hải": "Nguyễn Thị Lệ Hải",
}


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


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").replace("đ", "d")


def _periods_from_text(text: str) -> list[int]:
    """Extract a complete period range from common Vietnamese free text."""
    plain = _plain(text)
    ranges = re.findall(r"(?:tiet|ca|block)?\s*(\d{1,2})\s*(?:-|–|den|toi)\s*(\d{1,2})", plain)
    if ranges:
        start, end = map(int, ranges[0])
        return list(range(start, end + 1)) if 1 <= start <= end <= 15 else []
    # A number after "thứ" is a weekday, never a teaching period. Only accept
    # isolated periods when the text explicitly identifies them as a period.
    period_match = re.search(r"(?:tiet|ca|block)\s*(\d{1,2})", plain)
    if not period_match:
        return []
    period = int(period_match.group(1))
    return [period] if 1 <= period <= 15 else []


def describe_preference(constraint_type: str, target: dict) -> str:
    slots = target.get("slots") or []
    if slots:
        slot_labels = []
        for slot in slots:
            weekday = slot.get("weekday")
            periods = slot.get("periods") or []
            day = "Chủ Nhật" if weekday == 8 else f"Thứ {weekday}"
            period_label = f" tiết {min(periods)}–{max(periods)}" if periods else ""
            slot_labels.append(f"{day}{period_label}")
        labels = {
            "unavailable": "Không xếp lịch",
            "prefer_period": "Ưu tiên xếp lịch",
            "available": "Có thể xếp lịch",
            "seminar": "Giữ lịch seminar",
        }
        return f"{labels.get(constraint_type, 'Ràng buộc')} · {'; '.join(slot_labels)}"
    weekday = target.get("weekday")
    day = "mọi ngày" if weekday is None else ("Chủ Nhật" if weekday == 8 else f"Thứ {weekday}")
    periods = target.get("periods") or target.get("period_range") or []
    period_label = f", tiết {min(periods)}–{max(periods)}" if periods else ""
    labels = {
        "unavailable": "Không xếp lịch",
        "prefer_period": "Ưu tiên xếp lịch",
        "available": "Có thể xếp lịch",
        "seminar": "Giữ lịch seminar",
        "preferred_assignment": "Đề nghị phân công",
        "compact_schedule": "Ưu tiên lịch gọn",
        "raw_preference": "Cần trưởng bộ môn diễn giải",
    }
    return f"{labels.get(constraint_type, 'Ràng buộc')} · {day}{period_label}"


def _infer(text: str, weekday: int | None) -> tuple[str, dict, float]:
    lowered = _plain(text)
    periods = _periods_from_text(text)
    detected_weekday = weekday
    weekday_match = re.search(r"(?:thu|t)\s*([2-7])|chu\s*nhat", lowered)
    if weekday_match:
        detected_weekday = 8 if "chu" in weekday_match.group(0) else int(weekday_match.group(1))
    target = {"weekday": detected_weekday}
    if "seminar" in lowered:
        target["periods"] = periods[:2]
        confidence = 0.9 if detected_weekday is not None else 0.7
        target["analysis"] = {"confidence": confidence, "rule": "seminar"}
        return "seminar", target, confidence
    unavailable_tokens = ("xin nghi", "khong day", "khong the day", "khong xep", "ban", "tranh")
    if any(token in lowered for token in unavailable_tokens):
        target["periods"] = periods
        confidence = 0.9 if detected_weekday is not None else 0.65
        target["analysis"] = {"confidence": confidence, "rule": "unavailable"}
        return "unavailable", target, confidence
    has_assignment_verb = any(token in lowered for token in ("phan", "xep", "day"))
    has_assignment_target = any(token in lowered for token in ("lop", "mon", "hoc phan"))
    if has_assignment_verb and has_assignment_target:
        target["requested_assignment"] = text
        target["analysis"] = {"confidence": 0.72, "rule": "preferred_assignment"}
        return "preferred_assignment", target, 0.72
    if "sang" in lowered:
        target["period_range"] = [1, 6]
        target["analysis"] = {"confidence": 0.85, "rule": "prefer_period"}
        return "prefer_period", target, 0.85
    if "chieu" in lowered:
        target["period_range"] = [7, 12]
        target["analysis"] = {"confidence": 0.85, "rule": "prefer_period"}
        return "prefer_period", target, 0.85
    if any(token in lowered for token in ("lien", "gon", "it ngay")):
        target["analysis"] = {"confidence": 0.78, "rule": "compact_schedule"}
        return "compact_schedule", target, 0.78
    target["analysis"] = {"confidence": 0.35, "rule": "raw_preference"}
    return "raw_preference", target, 0.35


def parse_preferences(path: Path) -> list[ParsedPreference]:
    book = openpyxl.load_workbook(path, read_only=False, data_only=True)
    sheet = book[book.sheetnames[0]]
    result: list[ParsedPreference] = []
    for row in range(4, min(sheet.max_row, 1000) + 1):
        alias = clean_text(sheet.cell(row, 2).value)
        if not alias:
            continue
        canonical = ALIASES.get(alias.casefold(), alias)
        for column in range(3, 11):
            raw = clean_text(sheet.cell(row, column).value)
            if not raw:
                continue
            weekday = column - 1 if column <= 9 else None
            kind, target, confidence = _infer(raw, weekday)
            result.append(ParsedPreference(alias, canonical, weekday, kind, target, raw, confidence, row))
    return result
