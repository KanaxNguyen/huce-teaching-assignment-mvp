from datetime import date
from types import SimpleNamespace

from app.exporters.integrations import _escape_ics, _fold_ics_line, _session_dates


def test_session_dates_follow_active_academic_weeks():
    session = SimpleNamespace(
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 31),
        weekday=2,
        active_weeks=[1, 3, 5],
    )

    assert _session_dates(session) == [
        date(2026, 8, 3),
        date(2026, 8, 17),
        date(2026, 8, 31),
    ]


def test_ics_values_are_escaped():
    assert _escape_ics("Phòng A, tầng 2\nDãy 1") == "Phòng A\\, tầng 2\\nDãy 1"


def test_ics_lines_are_folded_by_utf8_octets():
    folded = _fold_ics_line("SUMMARY:" + "Giải tích nâng cao — " * 8)

    assert len(folded) > 1
    assert all(len(line.encode("utf-8")) <= 75 for line in folded)
    assert all(line.startswith(" ") for line in folded[1:])
