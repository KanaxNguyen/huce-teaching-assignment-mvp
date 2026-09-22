from pathlib import Path

from openpyxl import Workbook

from app.parsers.preferences import detect_preference_format, parse_preference_workbook


def _form(book: Workbook, title: str):
    sheet = book.create_sheet(title)
    sheet["A1"] = "[HUCE-FORM-PREF-V3.0]"
    return sheet


def test_grid_v3_reads_all_forms_and_only_explicit_scheduling_choices(tmp_path: Path):
    path = tmp_path / "preferences.xlsx"
    book = Workbook()
    book.active.title = "Tong_hop"  # A summary sheet must not stop individual-form parsing.

    alice = _form(book, "01_Alice Nguyen")
    alice["C14"] = "Bận cứng"
    alice["E21"] = "Bỏ trống nếu không có giới hạn"
    alice["F21"] = "Tối đa 3 ngày/tuần"
    alice["E22"] = "Chọn Rất mong muốn nếu cần ưu tiên"
    alice["F22"] = "Rất mong muốn"
    alice["E23"] = "Chọn Có nếu có nguyện vọng này"
    alice["F23"] = "Có"
    alice["A25"] = "Xin dạy ít"

    bob = _form(book, "02_Bob Tran")
    bob["E8"] = "Bob Tran"
    bob["D16"] = "Ưu tiên"
    bob["F22"] = "Chọn Rất mong muốn nếu cần ưu tiên"
    bob["F23"] = "Chọn Có nếu có nguyện vọng này"
    book.save(path)

    assert detect_preference_format(path) == "GRID_V3"
    result = parse_preference_workbook(path)
    assert result.format == "GRID_V3"

    alice_rules = [rule for rule in result.drafts if rule.lecturer_alias == "Alice Nguyen"]
    assert {rule.constraint_type for rule in alice_rules} == {
        "UNAVAILABLE", "MAX_DAYS_PER_WEEK", "PREFER_COMPACT_SCHEDULE", "MIN_FREE_MORNING_PER_WEEK",
        "PREFER_LOW_WORKLOAD", "RAW_NOTE",
    }
    assert all(rule.needs_review for rule in alice_rules if rule.constraint_type != "RAW_NOTE")
    unavailable = next(rule for rule in alice_rules if rule.constraint_type == "UNAVAILABLE")
    assert unavailable.day_scope == "T2" and unavailable.target["periods"] == [1, 2, 3]
    max_days = next(rule for rule in alice_rules if rule.constraint_type == "MAX_DAYS_PER_WEEK")
    assert max_days.numeric_value == 3 and max_days.source_cell == "F21"
    raw_note = next(rule for rule in alice_rules if rule.constraint_type == "RAW_NOTE")
    assert not raw_note.needs_review and raw_note.status == "INTERPRETED" and raw_note.weight == 0
    assert raw_note.target["interpreted_rules"][0]["constraint_type"] == "PREFER_LOW_WORKLOAD"

    bob_rules = [rule for rule in result.drafts if rule.lecturer_alias == "Bob Tran"]
    assert [rule.constraint_type for rule in bob_rules] == ["PREFERRED_PERIOD"]
    assert bob_rules[0].day_scope == "T3" and not bob_rules[0].needs_review
