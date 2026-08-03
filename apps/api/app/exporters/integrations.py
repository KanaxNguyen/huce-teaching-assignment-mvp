from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection
from app.services.settings import get_app_settings

PERIOD_TIMES: dict[int, tuple[int, int]] = {
    1: (7, 0),
    2: (7, 50),
    3: (8, 40),
    4: (9, 35),
    5: (10, 25),
    6: (11, 15),
    7: (13, 0),
    8: (13, 50),
    9: (14, 40),
    10: (15, 35),
    11: (16, 25),
    12: (17, 15),
    13: (18, 0),
    14: (18, 50),
    15: (19, 40),
}


def latest_assignments(db: Session, lecturer: str | None = None) -> list[Assignment]:
    latest = db.scalar(select(Assignment.run_id).order_by(Assignment.run_id.desc()).limit(1))
    if latest is None:
        raise ValueError("Chưa có kết quả tối ưu để xuất.")
    query = (
        select(Assignment)
        .where(Assignment.run_id == latest)
        .options(
            selectinload(Assignment.lecturer),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
        )
        .order_by(Assignment.id)
    )
    items = list(db.scalars(query).all())
    if lecturer:
        items = [item for item in items if item.lecturer.canonical_name == lecturer]
    if not items:
        raise ValueError("Không có dữ liệu phù hợp để xuất.")
    return items


def assignment_rows(db: Session, lecturer: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for assignment in latest_assignments(db, lecturer):
        section = assignment.class_section
        for session in section.sessions:
            rows.append(
                {
                    "course_code": section.course.code,
                    "course_name": section.course.name,
                    "class_code": section.class_code,
                    "merged_group": section.merged_group_id or "",
                    "lecturer": assignment.lecturer.canonical_name,
                    "weekday": session.weekday,
                    "start_period": session.start_period,
                    "end_period": session.end_period,
                    "room": session.room,
                    "start_date": session.start_date.isoformat() if session.start_date else None,
                    "end_date": session.end_date.isoformat() if session.end_date else None,
                    "weeks": session.active_weeks,
                    "locked": assignment.locked,
                }
            )
    return rows


def export_csv_bytes(db: Session, lecturer: str | None = None) -> bytes:
    rows = assignment_rows(db, lecturer)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def export_json_bytes(db: Session, lecturer: str | None = None) -> bytes:
    app_settings = get_app_settings(db)
    payload = {
        "schema_version": "1.0",
        "academic_year": app_settings.academic_year,
        "semester": app_settings.semester,
        "semester_start": app_settings.semester_start.isoformat() if app_settings.semester_start else None,
        "semester_end": app_settings.semester_end.isoformat() if app_settings.semester_end else None,
        "timezone": app_settings.timezone_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": assignment_rows(db, lecturer),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _escape_ics(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold_ics_line(value: str, limit: int = 75) -> list[str]:
    """Fold a content line without splitting a UTF-8 code point (RFC 5545 section 3.1)."""
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    for character in value:
        size = len(character.encode("utf-8"))
        allowed = limit if not chunks else limit - 1
        if current and current_bytes + size > allowed:
            chunks.append(current)
            current = character
            current_bytes = size
        else:
            current += character
            current_bytes += size
    if current or not chunks:
        chunks.append(current)
    return [chunks[0], *(f" {chunk}" for chunk in chunks[1:])]


def _first_session_date(start_date: date, weekday: int) -> date:
    iso_weekday = weekday - 1  # Dữ liệu dùng 2=Thứ Hai ... 8=Chủ Nhật.
    return start_date + timedelta(days=(iso_weekday - start_date.isoweekday()) % 7)


def _session_dates(session) -> list[date]:
    if not session.start_date:
        return []
    first = _first_session_date(session.start_date, session.weekday)
    if session.active_weeks:
        dates = [first + timedelta(weeks=max(int(week) - 1, 0)) for week in session.active_weeks]
    elif session.end_date:
        count = max(((session.end_date - first).days // 7) + 1, 1)
        dates = [first + timedelta(weeks=index) for index in range(count)]
    else:
        dates = [first]
    return [item for item in dates if not session.end_date or item <= session.end_date]


def export_ics_bytes(db: Session, lecturer: str | None = None) -> bytes:
    app_settings = get_app_settings(db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calendar_name = f"{app_settings.calendar_name} · HK{app_settings.semester} · {app_settings.academic_year}"
    timezone_name = app_settings.timezone_name
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//HUCE//Teaching Assignment {app_settings.academic_year}//VI",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics(calendar_name)}",
        f"X-WR-TIMEZONE:{timezone_name}",
    ]
    grouped: dict[str, list[Assignment]] = {}
    for assignment in latest_assignments(db, lecturer):
        section = assignment.class_section
        group_key = f"group-{section.merged_group_id}" if section.merged_group_id else f"class-{section.id}"
        grouped.setdefault(group_key, []).append(assignment)
    for group_key, assignments in grouped.items():
        assignment = assignments[0]
        section = assignment.class_section
        class_codes = " + ".join(sorted(item.class_section.class_code for item in assignments))
        for session in section.sessions:
            start_clock = PERIOD_TIMES.get(session.start_period, (7, 0))
            end_base = PERIOD_TIMES.get(session.end_period, start_clock)
            end_clock = (datetime.combine(date.today(), time(*end_base)) + timedelta(minutes=45)).time()
            for event_date in _session_dates(session):
                start_at = datetime.combine(event_date, time(*start_clock))
                end_at = datetime.combine(event_date, end_clock)
                uid = (
                    f"huce-{app_settings.academic_year}-{group_key}-{session.weekday}-"
                    f"{session.start_period}-{session.end_period}-{event_date.isoformat()}@tkb.huce.edu.vn"
                )
                description = (
                    f"Giảng viên: {assignment.lecturer.canonical_name}\n"
                    f"Lớp: {class_codes}\nTiết: {session.start_period}-{session.end_period}"
                )
                lines.extend(
                    [
                        "BEGIN:VEVENT",
                        f"UID:{uid}",
                        f"DTSTAMP:{stamp}",
                        f"DTSTART;TZID={timezone_name}:{start_at:%Y%m%dT%H%M%S}",
                        f"DTEND;TZID={timezone_name}:{end_at:%Y%m%dT%H%M%S}",
                        f"SUMMARY:{_escape_ics(section.course.name)} — {_escape_ics(class_codes)}",
                        f"LOCATION:{_escape_ics(session.room or 'Chưa xếp phòng')}",
                        f"DESCRIPTION:{_escape_ics(description)}",
                        "STATUS:CONFIRMED",
                        "TRANSP:OPAQUE",
                        "END:VEVENT",
                    ]
                )
    lines.append("END:VCALENDAR")
    folded = [folded_line for line in lines for folded_line in _fold_ics_line(line)]
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")
