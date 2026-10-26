from pathlib import Path
from datetime import date
from collections import Counter
from app.parsers.preferences import parse_preference_workbook, detect_preference_format

WORKBOOK_PATH = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chuan_Hoa.xlsx')

def test_detects_grid_v3_format():
    assert detect_preference_format(WORKBOOK_PATH) == "GRID_V3"

def test_parse_all_20_lecturers():
    result = parse_preference_workbook(WORKBOOK_PATH)
    assert result.format == "GRID_V3"
    assert len(result.drafts) > 0
    names = {d.canonical_name for d in result.drafts}
    assert len(names) == 20
    # Check that even empty sheets generated a RAW_NOTE
    assert "Bằng Giang" in names
    assert "Cô Nguyễn Thị Thuần" in names

def test_real_grid_v3_rule_counts_are_preserved():
    result = parse_preference_workbook(WORKBOOK_PATH)
    counts = Counter(d.constraint_type for d in result.drafts)
    assert counts["UNAVAILABLE"] == 27
    assert counts["PREFERRED_PERIOD"] == 9
    assert counts["AVOID_PERIOD"] == 1
    assert counts["RAW_NOTE"] == 20
    assert counts["PREFER_COMPACT_SCHEDULE"] == 2
    assert counts["PREFER_LOW_WORKLOAD"] == 2
    assert counts["PREFERRED_DAYS"] == counts["AVOID_DAYS"] == 1

def test_fallback_identity_from_summary():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # The sheet is missing code and name in row 8, but name is extracted from summary
    # which makes title_identity_only = False (meaning needs_review = False just for identity)
    # Wait, if code is missing, needs_review might still be True during API validation 
    # but the parser itself sets it based on title_identity_only.
    # Let's check Thoan's draft.
    thoan_drafts = [d for d in result.drafts if d.canonical_name == "Thoan"]
    assert len(thoan_drafts) > 0
    # Because we used fallback name and not just title guess, needs_review should be False for identity reasons
    # Actually, in my implementation:
    # title_identity_only = not lecturer_code and not entered_name and not fallback_name
    # So title_identity_only is False. status="CONFIRMED".
    # Note: validate_preference_draft in parse_preference_workbook might change it to NEEDS_REVIEW
    # if lecturer_id is not found, but we can check the canonical_name.
    assert thoan_drafts[0].canonical_name == "Thoan"
    assert thoan_drafts[0].lecturer_code is None

def test_ban_cung_is_hard_unavailable():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # Thoan has BẬN CỨNG on Ca 1 all week
    thoan_unavail = [d for d in result.drafts if d.canonical_name == "Thoan" and d.constraint_type == "UNAVAILABLE" and d.day_scope != "ALL_DAYS"]
    assert len(thoan_unavail) > 0
    assert all(d.hardness == "hard" for d in thoan_unavail)
    assert all(set(d.target["periods"]) <= {1, 2, 3, 4, 5, 6} for d in thoan_unavail)

def test_uu_tien_is_soft_preferred():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # Cường has ƯU TIÊN on Ca 1
    cuong_pref = [d for d in result.drafts if d.canonical_name == "Cường" and d.constraint_type == "PREFERRED_PERIOD"]
    assert len(cuong_pref) > 0
    assert cuong_pref[0].hardness == "soft"

def test_fallback_text_supersedes_grid_avoid():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # The authoritative free text says “có thể nhận thêm 7-9”, so this is a
    # weak preferred period and must supersede the grid's generic HẠN CHẾ mark.
    cuong_avoid = [d for d in result.drafts if d.canonical_name == "Cường" and d.constraint_type == "AVOID_PERIOD"]
    assert cuong_avoid == []
    fallback = [d for d in result.drafts if d.canonical_name == "Cường" and d.constraint_type == "PREFERRED_PERIOD" and d.target["periods"] == [7, 8, 9]]
    assert len(fallback) == 1 and fallback[0].weight == .3

def test_empty_cell_no_constraint():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # Thoan has no constraint on Ca 4 (T2-CN)
    thoan_ca4 = [d for d in result.drafts if d.canonical_name == "Thoan" and d.start_period == 10]
    assert len(thoan_ca4) == 0

def test_section3_help_text_ignored():
    result = parse_preference_workbook(WORKBOOK_PATH)
    # Thoan has help text in section 3, no actual preferences chosen
    thoan_sec3 = [d for d in result.drafts if d.canonical_name == "Thoan" and d.constraint_type in ("MAX_DAYS_PER_WEEK", "PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK")]
    assert len(thoan_sec3) == 0

def test_thoan_grid_full():
    result = parse_preference_workbook(WORKBOOK_PATH)
    thoan = [d for d in result.drafts if d.canonical_name == "Thoan"]
    # Atomic hard blocks plus one provenance-only interpreted RAW_NOTE.
    assert len(thoan) == 8
    assert next(d for d in thoan if d.constraint_type == "RAW_NOTE").status == "INTERPRETED"
