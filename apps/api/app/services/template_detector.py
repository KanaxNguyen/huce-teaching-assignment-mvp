from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from openpyxl.utils import get_column_letter

CANONICAL_FIELD_ALIASES: dict[str, set[str]] = {
    "stt": {"stt", "so thu tu", "so tt", "tt"},
    "course_code": {"ma hoc phan", "ma hp", "ma mon hoc", "ma mon", "hoc phan"},
    "course_name": {"ten mon hoc", "ten mon", "ten hoc phan", "mon hoc", "ten hp"},
    "class_code": {"ma lop hoc", "ma lop", "lop hoc", "lop"},
    "merged_class": {"lop ghep", "ma lop ghep", "nhom ghep"},
    "weekday": {"thu", "ngay hoc", "lich hoc thu", "thu hoc", "lich hoc > thu"},
    "periods": {"tiet hoc", "tiet", "ca hoc", "lich hoc tiet", "lich hoc tiet hoc", "lich hoc > tiet", "lich hoc > tiet hoc"},
    "room": {"phong hoc", "phong", "lich hoc phong hoc", "lich hoc phong", "lich hoc > phong hoc", "lich hoc > phong"},
    "credits": {"so tc", "so tin chi", "tin chi", "lich hoc so tc", "lich hoc > so tc", "tc"},
    "group": {"nhom", "nhom lop", "to", "lich hoc nhom", "lich hoc > nhom"},
    "start_date": {"bat dau", "ngay bat dau", "thoi gian hoc bat dau", "tg bat dau", "thoi gian hoc > bat dau"},
    "end_date": {"ket thuc", "ngay ket thuc", "thoi gian hoc ket thuc", "tg ket thuc", "thoi gian hoc > ket thuc"},
    "weeks": {"tuan hoc", "tuan", "lich tuan", "tuan hoc > tuan"},
    "lecturer": {"giang vien", "giao vien", "ho va ten", "ten giang vien", "ho ten giang vien", "cbgiang"},
}

REQUIRED_FIELDS = ("lecturer", "course_name", "class_code", "weekday", "periods")
CORE_HEADER_FIELDS = ("lecturer", "course_code", "course_name", "class_code", "weekday", "periods")


def _weekday(value: Any) -> int | None:
    normalized = _plain(value)
    if normalized in {"cn", "chu nhat", "chủ nhật"}:
        return 8
    match = re.fullmatch(r"(?:thu|thứ)\s*([2-7])", normalized)
    return int(match.group(1)) if match else None


def _plain(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip().casefold()
    text = text.replace("đ", "d")
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _read(path: Path) -> tuple[str, list[list[Any]], list[tuple[int, int, int, int]]]:
    """Read sheet name, rows, and merged cell ranges [rlo, rhi, clo, chi] (0-indexed half-open)."""
    if path.suffix.lower() == ".xls":
        try:
            book = xlrd.open_workbook(path, formatting_info=True)
            sheet = book.sheet_by_index(0)
            merged = [(rlo, rhi, clo, chi) for rlo, rhi, clo, chi in sheet.merged_cells]
        except Exception:
            book = xlrd.open_workbook(path)
            sheet = book.sheet_by_index(0)
            merged = []
        rows = [sheet.row_values(index)[:40] for index in range(min(sheet.nrows, 120))]
        return sheet.name, rows, merged

    book = openpyxl.load_workbook(path, data_only=True)
    sheet = book[book.sheetnames[0]]
    merged = []
    for cell_range in sheet.merged_cells.ranges:
        merged.append((cell_range.min_row - 1, cell_range.max_row, cell_range.min_col - 1, cell_range.max_col))
    rows = [
        list(row[:40])
        for row in sheet.iter_rows(
            min_row=1,
            max_row=min(sheet.max_row, 120),
            values_only=True,
        )
    ]
    sheet_name = sheet.title
    book.close()
    return sheet_name, rows, merged


def _build_propagated_grid(rows: list[list[Any]], merged: list[tuple[int, int, int, int]]) -> list[list[Any]]:
    nrows = len(rows)
    ncols = max((len(r) for r in rows), default=0)
    grid = [[rows[r][c] if c < len(rows[r]) else None for c in range(ncols)] for r in range(nrows)]
    for rlo, rhi, clo, chi in merged:
        if rlo < nrows and clo < ncols:
            val = rows[rlo][clo] if clo < len(rows[rlo]) else None
            if val is not None and str(val).strip():
                for r in range(rlo, min(rhi, nrows)):
                    for c in range(clo, min(chi, ncols)):
                        grid[r][c] = val
    return grid


def _match_column_header(composite: str, parent: str = "", child: str = "") -> tuple[str | None, float]:
    """Return matching canonical field and confidence level (1.0 = EXACT, 0.95 = HIGH, 0.8 = MEDIUM)."""
    p_comp = _plain(composite)
    p_child = _plain(child) if child else p_comp
    p_parent = _plain(parent)

    for field, aliases in CANONICAL_FIELD_ALIASES.items():
        plain_aliases = {_plain(a) for a in aliases}
        if p_comp in plain_aliases:
            return field, 1.0
        if p_child in plain_aliases:
            if p_parent and any(word in p_parent for word in ("lich", "thoi gian", "mon", "lop", "hoc", "thong tin")):
                return field, 1.0
            return field, 0.95
        if any(p_comp.endswith(" " + a) for a in plain_aliases):
            return field, 0.95

    return None, 0.0


def _validate_column_sample(field: str, sample_values: list[Any]) -> tuple[bool, float]:
    """Validate that sample data row values conform to domain expectations for the mapped field."""
    non_empty = [val for val in sample_values if val is not None and str(val).strip()]
    if not non_empty:
        return True, 1.0

    matches = 0
    total = len(non_empty)
    for val in non_empty:
        s = str(val).strip()
        if field == "weekday":
            if s in {"2", "3", "4", "5", "6", "7", "8", "cn"} or re.match(r"^(?:thu\s*)?[2-8]$", s, re.I):
                matches += 1
        elif field == "periods":
            m = re.match(r"^([1-9]|1[0-5])(?:\s*[\-–]\s*([1-9]|1[0-5]))?$", s)
            if m:
                p_start = int(m.group(1))
                p_end = int(m.group(2)) if m.group(2) else p_start
                if 1 <= p_start <= p_end <= 15:
                    matches += 1
        elif field == "course_code":
            if re.match(r"^[A-Za-z0-9_\.\-]{3,20}$", s):
                matches += 1
        elif field == "lecturer":
            if re.search(r"[A-Za-zÀ-ỹ]", s) and len(s) >= 3:
                matches += 1
        elif field in ("start_date", "end_date"):
            if isinstance(val, (int, float)) and 30000 < val < 60000:
                matches += 1
            elif re.search(r"\d{1,4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,4}", s):
                matches += 1
        elif field == "stt":
            if re.match(r"^\d+$", s):
                matches += 1
        else:
            matches += 1

    rate = matches / total
    return rate >= 0.35, rate


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
            "header_start_row": index + 1,
            "header_end_row": index + 1,
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
            "historical_summary": {
                "columns_count": len(weekday_columns) + 1,
                "data_rows_count": max(0, len(rows) - index - 1),
                "courses_count": 0,
                "classes_count": 0,
                "merged_groups_count": 0,
                "lecturers_count": len(preview),
                "lecturers_with_code": 0,
            },
        }
    return None


def detect_output_template(path: Path) -> dict:
    sheet_name, rows, merged = _read(path)
    matrix = _detect_matrix(rows)
    if matrix:
        if 'historical_summary' in matrix:
            matrix['historical_summary'].update(scope='DETECTION_SAMPLE',sample_rows_read=len(rows),sample_limit=120)
        return {
            "source_file": path.name,
            "source_sheet": sheet_name,
            **matrix,
        }

    nrows = len(rows)
    ncols = max((len(r) for r in rows), default=0)
    grid = _build_propagated_grid(rows, merged)

    best_score = -1
    best_window = (0, 0)
    best_mappings: dict[str, dict[str, Any]] = {}
    best_headers: list[str] = []

    # Search for optimal header band window (length 1, 2, or 3 rows)
    for r_start in range(min(nrows, 35)):
        for length in (1, 2, 3):
            r_end = r_start + length - 1
            if r_end >= nrows:
                continue

            headers: list[str] = []
            parents: list[str] = []
            children: list[str] = []
            for c in range(ncols):
                parts: list[str] = []
                for r in range(r_start, r_end + 1):
                    v = str(grid[r][c] or "").strip()
                    if not v or re.fullmatch(r"[0-9\s\-–]+", v):
                        continue
                    if not parts or parts[-1] != v:
                        parts.append(v)
                if not parts:
                    for r in range(r_start, r_end + 1):
                        v = str(rows[r][c] or "").strip()
                        if v and (not parts or parts[-1] != v):
                            parts.append(v)
                comp = " > ".join(parts) if parts else ""
                headers.append(comp)
                parents.append(parts[0] if parts else "")
                children.append(parts[-1] if parts else "")

            matches: dict[str, dict[str, Any]] = {}
            for c in range(ncols):
                h = headers[c]
                if not h:
                    continue
                field, conf = _match_column_header(h, parents[c], children[c])
                if field and field not in matches:
                    samples = [rows[r][c] for r in range(r_end + 1, min(nrows, r_end + 16)) if c < len(rows[r])]
                    valid, _ = _validate_column_sample(field, samples)
                    if not valid:
                        conf = round(conf * 0.5, 2)
                    matches[field] = {
                        "column_index": c + 1,
                        "column_letter": get_column_letter(c + 1),
                        "header": h,
                        "confidence": conf,
                    }

            req_matched = [f for f in CORE_HEADER_FIELDS if f in matches and matches[f]["confidence"] >= 0.7]
            composite_bonus = 20 if any(" > " in h for h in headers) else 0
            score = len(req_matched) * 100 + len(matches) * 10 + composite_bonus - length
            if score > best_score:
                best_score = score
                best_window = (r_start, r_end)
                best_mappings = matches
                best_headers = headers

    r_start, r_end = best_window
    header_start_row = r_start + 1
    header_end_row = r_end + 1

    available_columns = [
        {
            "column_index": c + 1,
            "column_letter": get_column_letter(c + 1),
            "header": best_headers[c] or f"Cột {get_column_letter(c + 1)}",
        }
        for c in range(ncols)
        if c < len(best_headers) and best_headers[c]
    ]

    preview = []
    for r in range(header_end_row, min(nrows, header_end_row + 5)):
        row_data = rows[r]
        preview.append(
            {
                field: str(row_data[item["column_index"] - 1] or "").strip()
                if item["column_index"] - 1 < len(row_data)
                else ""
                for field, item in best_mappings.items()
            }
        )

    missing = [field for field in REQUIRED_FIELDS if field not in best_mappings or best_mappings[field]["confidence"] < 0.7]

    # Compute dynamic historical summary metrics from the data rows
    courses = set()
    classes = set()
    merged_groups = set()
    lecturers = set()
    lecturers_with_code = set()
    data_rows_count = 0

    c_col = best_mappings.get("course_code", {}).get("column_index")
    cls_col = best_mappings.get("class_code", {}).get("column_index")
    mg_col = best_mappings.get("merged_class", {}).get("column_index")
    lec_col = best_mappings.get("lecturer", {}).get("column_index")

    for r in range(header_end_row, nrows):
        row_data = rows[r]
        if not any(row_data):
            continue
        data_rows_count += 1
        if c_col and c_col - 1 < len(row_data) and row_data[c_col - 1]:
            courses.add(str(row_data[c_col - 1]).strip())
        if cls_col and cls_col - 1 < len(row_data) and row_data[cls_col - 1]:
            classes.add(str(row_data[cls_col - 1]).strip())
        if mg_col and mg_col - 1 < len(row_data) and row_data[mg_col - 1]:
            merged_groups.add(str(row_data[mg_col - 1]).strip())
        if lec_col and lec_col - 1 < len(row_data) and row_data[lec_col - 1]:
            val = str(row_data[lec_col - 1]).strip()
            if val and val.lower() not in {"chưa phân công", "chua phan cong", "none"}:
                for part in re.split(r"[\n,]+", val):
                    part = part.strip()
                    if part:
                        lecturers.add(part)
                        if re.match(r"^\[.*?\]", part):
                            lecturers_with_code.add(part)

    historical_summary = {
        "scope": "DETECTION_SAMPLE",
        "sample_rows_read": len(rows),
        "sample_limit": 120,
        "columns_count": len(available_columns),
        "data_rows_count": data_rows_count,
        "courses_count": len(courses),
        "classes_count": len(classes),
        "merged_groups_count": len(merged_groups),
        "lecturers_count": len(lecturers),
        "lecturers_with_code": len(lecturers_with_code),
    }

    return {
        "source_file": path.name,
        "source_sheet": sheet_name,
        "layout": "table",
        "layout_label": "Bảng dữ liệu theo cột",
        "header_row": header_end_row,
        "header_start_row": header_start_row,
        "header_end_row": header_end_row,
        "mappings": best_mappings,
        "missing_fields": missing,
        "available_columns": available_columns,
        "preview": preview,
        "weekday_columns": [],
        "ready": len(missing) == 0,
        "historical_summary": historical_summary,
    }
