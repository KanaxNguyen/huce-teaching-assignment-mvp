from pathlib import Path

from app.parsers.schedule import decode_weeks, parse_schedule


def test_week_decoder_preserves_positions():
    raw, active = decode_weeks("1234 678  12345678")
    assert raw == "1234 678  12345678"
    assert active == [1, 2, 3, 4, 6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18]


def test_parse_real_schedule_when_present():
    path = Path(__file__).resolve().parents[3] / "data/local/source/schedule-2026-07-28.xls"
    if not path.exists():
        return
    result = parse_schedule(path)
    assert result.rows_accepted > 300
    assert len(result.classes) > 170
    assert sum(item.locked_assignment for item in result.classes) > 30
    assert result.merged_groups
