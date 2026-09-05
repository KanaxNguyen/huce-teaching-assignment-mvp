from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from openpyxl.utils import get_column_letter

FIELD_ALIASES = {
    "lecturer": {"giang vien", "giảng viên", "ho va ten", "họ và tên", "ten giang vien", "tên giảng viên"},
    "course_code": {"ma hoc phan", "mã học phần", "ma hp", "mã hp"},
    "course_name": {"ten mon hoc", "tên môn học", "mon hoc", "môn học"},
    "class_code": {"ma lop hoc", "mã lớp học", "ma lop", "mã lớp", "lop", "lớp"},
    "weekday": {"thu", "thứ", "ngay hoc", "ngày học"},
    "periods": {"tiet hoc", "tiết học", "tiet", "tiết", "ca hoc", "ca học"},
    "room": {"phong hoc", "phòng học", "phong", "phòng"},
    "weeks": {"tuan hoc", "tuần học", "tuan", "tuần"},
}

REQUIRED_FIELDS = ("lecturer", "course_name", "class_code", "weekday", "periods")


def _weekday(value: Any) -> int | None:
    normalized = _plain(value)
    if normalized in {"cn", "chu nhat", "chủ nhật"}:
        return 8
    match = re.fullmatch(r"(?:thu|thứ)\s*([2-7])", normalized)
    return int(match.group(1)) if match else None


def _detect_matrix(rows: list[list[Any]]) -> dict | None:
    """Detect the lecturer-by-weekday layout used by HUCE timetable exports."""
    for index, row in enumerate(rows[:40]):
        lecturer_column = next(
            (
                column
                for column, raw in enumerate(row)
                if "giang vien" in _plain(raw) and ("thu" in _plain(raw) or "ngay" in _plain(raw))
            ),
            None,
        )
        weekday_columns = [
            {
                "weekday": weekday,
                "column_index": column + 1,
                "column_letter": get_column_letter(column + 1),
                "header": str(raw or "").strip(),
            }
            for column, raw in enumerate(row)
            if (weekday := _weekday(raw)) is not None
        ]
        if lecturer_column is None or len(weekday_columns) < 2:
            continue

        preview = []
        for data_row in rows[index + 1 : index + 6]:
            lecturer = str(data_row[lecturer_column] or "").strip() if lecturer_column < len(data_row) else ""
            populated_days = [
                item["header"]
                for item in weekday_columns
                if item["column_index"] - 1 < len(data_row)
                and str(data_row[item["column_index"] - 1] or "").strip()
            ]
            if lecturer:
                preview.append({"lecturer": lecturer, "schedule_days": ", ".join(populated_days)})

        return {
            "layout": "matrix",
            "layout_label": "Ma trận giảng viên × ngày trong tuần",
            "header_row": index + 1,
            "mappings": {
                "lecturer": {
                    "column_index": lecturer_column + 1,
                    "column_letter": get_column_letter(lecturer_column + 1),
                    "header": str(row[lecturer_column] or "").strip(),
                    "confidence": 1.0,
                }
            },
            "missing_fields": [],
            "available_columns": [
                {
                    "column_index": lecturer_column + 1,
                    "column_letter": get_column_letter(lecturer_column + 1),
                    "header": str(row[lecturer_column] or "").strip(),
                },
                *weekday_columns,
            ],
            "weekday_columns": weekday_columns,
            "preview": preview,
            "ready": True,
        }
    return None


def _plain(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip().casefold()
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _read(path: Path) -> tuple[str, list[list[Any]]]:
    if path.suffix.lower() == ".xls":
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_index(0)
        return sheet.name, [sheet.row_values(index)[:40] for index in range(min(sheet.nrows, 80))]
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book[book.sheetnames[0]]
    rows = [
        list(row[:40])
        for row in sheet.iter_rows(
            min_row=1,
            max_row=min(sheet.max_row, 80),
            values_only=True,
        )
    ]
    sheet_name = sheet.title
    book.close()
    return sheet_name, rows


def detect_output_template(path: Path) -> dict:
    sheet_name, rows = _read(path)
    matrix = _detect_matrix(rows)
    if matrix:
        return {
            "source_file": path.name,
            "source_sheet": sheet_name,
            **matrix,
        }

    best_index = 0
    best_matches: dict[str, int] = {}
    for index, row in enumerate(rows[:40]):
        matches: dict[str, int] = {}
        for column, raw in enumerate(row):
            normalized = _plain(raw)
            if not normalized:
                continue
            for field, aliases in FIELD_ALIASES.items():
                if normalized in {_plain(alias) for alias in aliases} and field not in matches:
                    matches[field] = column
        if len(matches) > len(best_matches):
            best_index, best_matches = index, matches

    mappings = {}
    header = rows[best_index] if rows else []
    for field, column in best_matches.items():
        mappings[field] = {
            "column_index": column + 1,
            "column_letter": get_column_letter(column + 1),
            "header": str(header[column] or "").strip(),
            "confidence": 1.0,
        }

    preview = []
    for row in rows[best_index + 1 : best_index + 6]:
        preview.append(
            {
                field: str(row[item["column_index"] - 1] or "").strip()
                if item["column_index"] - 1 < len(row)
                else ""
                for field, item in mappings.items()
            }
        )

    missing = [field for field in REQUIRED_FIELDS if field not in mappings]
    return {
        "source_file": path.name,
        "source_sheet": sheet_name,
        "layout": "table",
        "layout_label": "Bảng dữ liệu theo cột",
        "header_row": best_index + 1,
        "mappings": mappings,
        "missing_fields": missing,
        "available_columns": [
            {
                "column_index": index + 1,
                "column_letter": get_column_letter(index + 1),
                "header": str(value or "").strip(),
            }
            for index, value in enumerate(header)
            if str(value or "").strip()
        ],
        "preview": preview,
        "weekday_columns": [],
        "ready": not missing,
    }
