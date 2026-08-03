from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import AppSetting, ClassSession


def get_app_settings(db: Session) -> AppSetting:
    item = db.get(AppSetting, 1)
    if item is None:
        item = AppSetting(id=1)
        db.add(item)
        db.commit()
        db.refresh(item)
    if item.semester_start is None or item.semester_end is None:
        earliest, latest = db.execute(
            select(func.min(ClassSession.start_date), func.max(ClassSession.end_date))
        ).one()
        if earliest or latest:
            item.semester_start = item.semester_start or earliest
            item.semester_end = item.semester_end or latest
            db.commit()
            db.refresh(item)
    return item


def settings_payload(item: AppSetting) -> dict:
    return {
        "academic_year": item.academic_year,
        "semester": item.semester,
        "semester_start": item.semester_start,
        "semester_end": item.semester_end,
        "institution": item.institution,
        "department": item.department,
        "calendar_name": item.calendar_name,
        "timezone_name": item.timezone_name,
        "primary_lecturer": item.primary_lecturer,
        "updated_at": item.updated_at,
    }
