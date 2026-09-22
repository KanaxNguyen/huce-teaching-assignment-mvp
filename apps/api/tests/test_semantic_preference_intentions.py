from datetime import date

from app.parsers.preferences import interpret_raw_preference


def _rules(text):
    return interpret_raw_preference(text, semester_start=date(2026, 9, 1), semester_end=date(2027, 1, 31))


def test_compact_days_are_atomic_and_normalized():
    rules = _rules("Xin ghép dạy gọn trong các ngày T3, 5, 6,7 vì T2,4 có lịch seminar")
    assert any(r["constraint_type"] == "PREFERRED_DAYS" and r["target"]["weekdays"] == [3, 5, 6, 7] for r in rules)
    assert any(r["constraint_type"] == "AVOID_DAYS" and r["target"]["weekdays"] == [2, 4] for r in rules)
    assert any(r["constraint_type"] == "PREFER_COMPACT_SCHEDULE" for r in rules)


def test_fallback_period_is_preferred_not_avoided():
    rules = _rules("Dạy các buổi sáng trong tuần, có thể nhận thêm tiết 7-9")
    assert any(r["constraint_type"] == "PREFERRED_PERIOD" and r["target"]["periods"] == list(range(1, 7)) and r["weight"] == .8 for r in rules)
    assert any(r["constraint_type"] == "PREFERRED_PERIOD" and r["target"]["periods"] == [7, 8, 9] and r["weight"] == .3 for r in rules)
    assert not any(r["constraint_type"] == "AVOID_PERIOD" for r in rules)


def test_soft_date_low_workload_and_explicit_seminar():
    rules = _rules("Xin tránh tiết 1-3; xin nghỉ đến 11 tháng 10 vì có lịch học ở Sư phạm (hoặc dạy ít); Seminar 4-6 thứ 5.")
    assert any(r["constraint_type"] == "AVOID_PERIOD" for r in rules)
    low = next(r for r in rules if r["constraint_type"] == "PREFER_LOW_WORKLOAD")
    assert low["hardness"] == "soft" and low["target"]["end_date"] == "2026-10-11"
    assert any(r["constraint_type"] == "UNAVAILABLE" and r["target"]["periods"] == [4, 5, 6] for r in rules)


def test_partial_seminar_morning_blocks_first_three_blocks():
    rules = _rules("T5 sáng seminar (có thể đến 12h30), chiều có thể dạy từ tiết 10")
    blocked = [r["target"]["periods"] for r in rules if r["constraint_type"] == "UNAVAILABLE"]
    assert blocked == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
