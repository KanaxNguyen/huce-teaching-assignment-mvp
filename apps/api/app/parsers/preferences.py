from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from app.parsers.schedule import clean_text

ALIASES = {
    "thoan": "Phạm Đức Thoan",
    "bằng giang": "Nguyễn Bằng Giang",
    "giang": "Nguyễn Bằng Giang",
    "x linh": "Nguyễn Xuân Linh",
    "kiều linh": "Kiều Thị Thùy Linh",
    "klinh": "Kiều Thị Thùy Linh",
    "mai hồng": "Mai Hồng",
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


def _infer(text: str, weekday: int | None) -> tuple[str, dict, float]:
    lowered = text.casefold()
    periods = [int(value) for value in re.findall(r"\d+", lowered)]
    if "seminar" in lowered:
        return "seminar", {"weekday": weekday, "periods": periods[:2]}, 0.9
    if any(token in lowered for token in ("xin nghỉ", "không dạy", "tránh")):
        return "unavailable", {"weekday": weekday, "periods": periods}, 0.75
    if "sáng" in lowered:
        return "prefer_period", {"weekday": weekday, "period_range": [1, 6]}, 0.8
    if "chiều" in lowered:
        return "prefer_period", {"weekday": weekday, "period_range": [7, 12]}, 0.8
    if "liền" in lowered:
        return "compact_schedule", {"weekday": weekday}, 0.7
    return "raw_preference", {"weekday": weekday}, 0.4


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
