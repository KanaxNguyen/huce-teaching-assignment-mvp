from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Course,
    ImportBatch,
    Lecturer,
    OptimizationRun,
    Seminar,
    ValidationIssue,
)
from app.parsers.preferences import parse_preferences
from app.parsers.schedule import ScheduleParseResult, parse_schedule


def _clear_imported_data(db: Session) -> None:
    for model in (
        Assignment,
        OptimizationRun,
        ClassSession,
        ClassSection,
        Course,
        Constraint,
        Seminar,
        Lecturer,
        ValidationIssue,
    ):
        db.execute(delete(model))
    db.flush()


def import_files(
    db: Session,
    paths: list[Path],
    *,
    schedule_paths: list[Path] | None = None,
    preference_paths: list[Path] | None = None,
) -> dict:
    schedule_paths = schedule_paths or [path for path in paths if "schedule" in path.name.casefold()]
    preference_paths = preference_paths or [path for path in paths if "preference" in path.name.casefold()]
    if not schedule_paths:
        raise ValueError("Cần ít nhất một file lịch học")
    primary = sorted(schedule_paths)[-1]
    parsed = parse_schedule(primary)

    _clear_imported_data(db)
    lecturers_by_name: dict[str, Lecturer] = {}
    lecturers_by_code: dict[str, Lecturer] = {}

    def ensure_lecturer(code: str | None, name: str, alias: str | None = None) -> Lecturer:
        lookup = lecturers_by_code.get(code) if code else None
        lookup = lookup or lecturers_by_name.get(name.casefold())
        if lookup:
            aliases = set(lookup.aliases or [])
            if alias:
                aliases.add(alias)
            lookup.aliases = sorted(aliases)
            return lookup
        lecturer = Lecturer(
            code=code,
            canonical_name=name,
            aliases=[alias] if alias and alias.casefold() != name.casefold() else [],
            confirmed=bool(code),
            source_file=primary.name,
        )
        db.add(lecturer)
        db.flush()
        lecturers_by_name[name.casefold()] = lecturer
        if code:
            lecturers_by_code[code] = lecturer
        return lecturer

    unmatched = set()
    for preference_path in preference_paths:
        for preference in parse_preferences(preference_path):
            lecturer = ensure_lecturer(None, preference.canonical_name, preference.lecturer_alias)
            if preference.confidence < 0.6:
                unmatched.add(preference.lecturer_alias)
            db.add(
                Constraint(
                    name=f"Nguyện vọng: {preference.lecturer_alias}",
                    constraint_type=preference.constraint_type,
                    hardness="soft",
                    weight=0.8,
                    lecturer_id=lecturer.id,
                    target=preference.target,
                    raw_text=preference.raw_text,
                    confirmed=preference.confidence >= 0.8,
                )
            )

    db.add_all(
        [
            Seminar(
                name="Seminar Bộ môn",
                chair_name="Phạm Đức Thoan",
                members=[
                    "Nguyễn Thị Thủy",
                    "Nguyễn Văn Tuyên",
                    "Trần Thị Liễu",
                    "Vũ Thị Hương Giang",
                    "Phạm Đức Thoan",
                    "Trần Văn Khiên",
                    "Kiều Thị Thùy Linh",
                    "Vũ Thị Ngân",
                ],
                alternatives=[
                    {"weekday": 5, "start_period": 4, "end_period": 6},
                    {"weekday": 4, "start_period": 4, "end_period": 6},
                ],
                weight=0.8,
                hardness="soft",
            ),
            Seminar(
                name="Seminar Giáo trình",
                chair_name="Nguyễn Bằng Giang",
                members=[
                    "Nguyễn Thị Thủy",
                    "Trần Thị Liễu",
                    "Vũ Thị Hương Giang",
                    "Kiều Thị Thùy Linh",
                    "Vũ Thị Ngân",
                    "Nguyễn Thị Lệ Hải",
                ],
                alternatives=[
                    {"weekday": weekday, "start_period": start, "end_period": end}
                    for weekday in range(2, 8)
                    for start, end in ((4, 6), (10, 12))
                ],
                weight=0.8,
                hardness="soft",
            ),
        ]
    )

    for item in parsed.classes:
        if item.lecturer_name:
            ensure_lecturer(item.lecturer_code, item.lecturer_name)

    courses: dict[str, Course] = {}
    for item in parsed.classes:
        course = courses.get(item.course_code)
        if not course:
            course = Course(code=item.course_code, name=item.course_name)
            db.add(course)
            db.flush()
            courses[item.course_code] = course
        lecturer = None
        if item.lecturer_name:
            lecturer = lecturers_by_code.get(item.lecturer_code) if item.lecturer_code else None
            lecturer = lecturer or lecturers_by_name.get(item.lecturer_name.casefold())
        section = ClassSection(
            course_id=course.id,
            class_code=item.class_code,
            credits=item.credits,
            merged_group_id=item.merged_group_id,
            locked_assignment=item.locked_assignment,
            assigned_lecturer_id=lecturer.id if lecturer else None,
            source_file=item.source_file,
            source_sheet=item.source_sheet,
            source_row=item.source_row,
            raw_values=item.raw_values,
        )
        db.add(section)
        db.flush()
        for session in item.sessions:
            db.add(
                ClassSession(
                    class_id=section.id,
                    weekday=session.weekday,
                    start_period=session.start_period,
                    end_period=session.end_period,
                    room=session.room,
                    start_date=session.start_date,
                    end_date=session.end_date,
                    raw_weeks=session.raw_weeks,
                    active_weeks=session.active_weeks,
                    source_row=session.source_row,
                )
            )

    for issue in parsed.issues:
        db.add(
            ValidationIssue(
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                source_file=issue.source_file,
                source_sheet=issue.source_sheet,
                source_row=issue.source_row,
                field=issue.field,
                raw_value=issue.raw_value,
                suggestion=issue.suggestion,
            )
        )

    summary = _summary(parsed)
    batch = ImportBatch(source_files=[path.name for path in paths], summary=summary)
    db.add(batch)
    db.commit()
    return {
        "batch_id": batch.id,
        "files": [path.name for path in paths],
        "summary": summary,
        "unmatched_lecturers": sorted(unmatched),
        "serious_errors": sum(1 for issue in parsed.issues if issue.severity == "error"),
        "preview": [
            {
                "course_code": item.course_code,
                "course_name": item.course_name,
                "class_code": item.class_code,
                "sessions": len(item.sessions),
                "lecturer": item.lecturer_name,
                "locked": item.locked_assignment,
                "merged_group_id": item.merged_group_id,
            }
            for item in parsed.classes[:12]
        ],
    }


def _summary(parsed: ScheduleParseResult) -> dict:
    merged_classes = {key for group in parsed.merged_groups for key in group.class_keys}
    return {
        "rows_read": parsed.rows_accepted + parsed.rows_rejected,
        "rows_accepted": parsed.rows_accepted,
        "rows_rejected": parsed.rows_rejected,
        "classes": len(parsed.classes),
        "sessions": sum(len(item.sessions) for item in parsed.classes),
        "single_classes": len(parsed.classes) - len(merged_classes),
        "merged_groups_suggested": len(parsed.merged_groups),
        "merged_pairs_suggested": sum(
            len(group.class_keys) * (len(group.class_keys) - 1) // 2 for group in parsed.merged_groups
        ),
        "locked_classes": sum(1 for item in parsed.classes if item.locked_assignment),
        "unassigned_classes": sum(1 for item in parsed.classes if not item.locked_assignment),
        "validation_errors": sum(1 for issue in parsed.issues if issue.severity == "error"),
    }


def dashboard(db: Session) -> dict:
    classes = db.scalars(select(ClassSection)).all()
    issues = db.scalars(select(ValidationIssue)).all()
    lecturers = db.scalars(select(Lecturer)).all()
    latest = db.scalars(select(OptimizationRun).order_by(OptimizationRun.id.desc())).first()
    return {
        "classes": len(classes),
        "locked_classes": sum(item.locked_assignment for item in classes),
        "unassigned_classes": sum(item.assigned_lecturer_id is None for item in classes),
        "merged_suggestions": len({item.merged_group_id for item in classes if item.merged_group_id}),
        "lecturers": len(lecturers),
        "validation_errors": sum(issue.severity == "error" for issue in issues),
        "optimization_status": latest.status if latest else "not_run",
        "optimization_score": latest.score if latest else None,
    }
