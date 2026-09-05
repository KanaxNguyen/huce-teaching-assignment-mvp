from __future__ import annotations

import unicodedata
from collections import defaultdict
from math import ceil
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
    LecturerCourseCapability,
    Lecturer,
    OptimizationRun,
    Seminar,
    ValidationIssue,
)
from app.parsers.preferences import describe_preference, parse_preferences
from app.parsers.schedule import ScheduleParseResult, parse_schedule


def _name_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return {token for token in plain.replace("đ", "d").split() if token}


def _clear_imported_data(db: Session, semester_id: int) -> None:
    class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.semester_id == semester_id)))
    if class_ids:
        db.execute(delete(ClassSession).where(ClassSession.class_id.in_(class_ids)))
    for model in (Assignment, OptimizationRun, ClassSection, Constraint, Seminar, ValidationIssue):
        db.execute(delete(model).where(model.semester_id == semester_id))
    db.flush()


def _import_files_impl(
    db: Session,
    paths: list[Path],
    *,
    semester_id: int,
    schedule_paths: list[Path] | None = None,
    preference_paths: list[Path] | None = None,
) -> dict:
    schedule_paths = schedule_paths or [path for path in paths if "schedule" in path.name.casefold()]
    preference_paths = preference_paths or [path for path in paths if "preference" in path.name.casefold()]
    if not schedule_paths:
        raise ValueError("Cần ít nhất một file lịch học")
    primary = sorted(schedule_paths)[-1]
    parsed = parse_schedule(primary)

    with db.begin_nested():
        _clear_imported_data(db, semester_id)
    lecturers_by_name = {item.canonical_name.casefold(): item for item in db.scalars(select(Lecturer)).all()}
    lecturers_by_code = {item.code: item for item in db.scalars(select(Lecturer)).all() if item.code}

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

    for item in parsed.classes:
        if item.lecturer_name:
            ensure_lecturer(item.lecturer_code, item.lecturer_name)

    unmatched = set()
    for preference_path in preference_paths:
        for preference in parse_preferences(preference_path):
            lecturer = lecturers_by_name.get(preference.canonical_name.casefold())
            if not lecturer:
                lecturer = None
            if lecturer:
                aliases = set(lecturer.aliases or [])
                aliases.add(preference.lecturer_alias)
                lecturer.aliases = sorted(aliases)
            else:
                lecturer = ensure_lecturer(None, preference.canonical_name, preference.lecturer_alias)
                unmatched.add(preference.lecturer_alias)
                db.add(ValidationIssue(
                    semester_id=semester_id,
                    severity="error",
                    code="LECTURER_IDENTITY_AMBIGUOUS",
                    message=f"Không xác định chắc chắn giảng viên cho '{preference.lecturer_alias}'.",
                    source_file=preference_path.name,
                    source_row=preference.source_row,
                    raw_value=preference.raw_text,
                    suggestion="Xác nhận mã hoặc tên đầy đủ trước khi tối ưu.",
                ))
            db.add(
                Constraint(
                    name=describe_preference(preference.constraint_type, preference.target),
                    constraint_type=preference.constraint_type,
                    hardness="soft",
                    weight=0.8,
                    lecturer_id=lecturer.id,
                    target=preference.target,
                    raw_text=preference.raw_text,
                    confirmed=preference.confidence >= 0.8,
                    semester_id=semester_id,
                )
            )

    courses: dict[str, Course] = {item.code: item for item in db.scalars(select(Course)).all()}
    locked_loads: dict[int, float] = defaultdict(float)
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
            semester_id=semester_id,
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
        if lecturer:
            capability = db.scalar(select(LecturerCourseCapability).where(
                LecturerCourseCapability.lecturer_id == lecturer.id,
                LecturerCourseCapability.course_id == course.id,
            ))
            if capability is None:
                db.add(LecturerCourseCapability(
                    lecturer_id=lecturer.id,
                    course_id=course.id,
                    allowed=True,
                    confirmed=item.locked_assignment,
                    source=primary.name,
                ))
        if lecturer and item.locked_assignment:
            locked_loads[lecturer.id] += item.credits
        seen_meetings = set()
        for session in item.sessions:
            signature = session.signature()
            if signature in seen_meetings:
                continue
            seen_meetings.add(signature)
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

    # Existing assignments are authoritative input. The provisional cap covers
    # total credits plus a 35% timetable buffer, because fixed timetable slots
    # prevent a perfectly even distribution. A later workload policy can lower
    # or raise this default explicitly.
    baseline_capacity = (
        ceil((sum(item.credits for item in parsed.classes) / len(lecturers_by_name)) * 1.35)
        if lecturers_by_name
        else 24
    )
    for lecturer in lecturers_by_name.values():
        lecturer.max_credits = max(
            lecturer.max_credits,
            float(baseline_capacity),
            locked_loads[lecturer.id],
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
                semester_id=semester_id,
            )
        )

    summary = _summary(parsed)
    batch = ImportBatch(semester_id=semester_id, source_files=[path.name for path in paths], summary=summary)
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


def import_files(
    db: Session,
    paths: list[Path],
    *,
    semester_id: int,
    schedule_paths: list[Path] | None = None,
    preference_paths: list[Path] | None = None,
) -> dict:
    """Persist one logical import with one final commit and rollback on failure."""
    try:
        return _import_files_impl(
            db,
            paths,
            semester_id=semester_id,
            schedule_paths=schedule_paths,
            preference_paths=preference_paths,
        )
    except Exception:
        db.rollback()
        raise


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


def dashboard(db: Session, semester_id: int) -> dict:
    classes = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    issues = db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == semester_id)).all()
    lecturers = db.scalars(select(Lecturer)).all()
    run_query = select(OptimizationRun).order_by(OptimizationRun.id.desc())
    run_query = run_query.where(OptimizationRun.semester_id == semester_id)
    latest = db.scalars(run_query).first()
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
