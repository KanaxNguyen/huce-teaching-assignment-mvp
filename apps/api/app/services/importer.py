from __future__ import annotations

import unicodedata
from collections import defaultdict
from math import ceil
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Course,
    Department,
    DepartmentProfile,
    ImportBatch,
    LecturerCourseCapability,
    Lecturer,
    NormalizedPreferenceDraft,
    OptimizationRun,
    Semester,
    SourceVersion,
    ValidationIssue,
)
from app.parsers.preferences import PreferenceParseResult, parse_preference_workbook, parse_preferences
from app.parsers.schedule import ScheduleParseResult, parse_schedule
from app.services.lecturer_master import resolve_identity


_ORIGINAL_PARSE_PREFERENCES = parse_preferences


def _parse_preference_source(path: Path, semester: Semester) -> PreferenceParseResult:
    """Keep old test/integration monkeypatches working while V2 uses rich results."""
    if parse_preferences is not _ORIGINAL_PARSE_PREFERENCES:
        drafts = parse_preferences(path)
        return PreferenceParseResult(format="LEGACY", drafts=drafts, raw_clauses=len(drafts))
    return parse_preference_workbook(path, semester_start=semester.start_date, semester_end=semester.end_date)


def _name_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return {token for token in plain.replace("đ", "d").split() if token}


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in normalized if unicodedata.category(char) != "Mn").replace("đ", "d")
    return " ".join(plain.split())


def _clear_imported_data(db: Session, semester_id: int) -> None:
    from app.services.source_authority import archive_schedule
    archive_schedule(db, semester_id)
    class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.semester_id == semester_id)))
    if class_ids:
        db.execute(delete(ClassSession).where(ClassSession.class_id.in_(class_ids)))
    for model in (Assignment, ClassSection):
        db.execute(delete(model).where(model.semester_id == semester_id))
    # Preference drafts have stable source keys and are reconciled separately.
    for issue in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == semester_id)):
        if issue.source_version_id is None or issue.source_version_id == db.get(Semester, semester_id).active_schedule_source_id:
            issue.resolution_status = "SUPERSEDED"
    db.flush()


def _materialize_impl(
    db: Session,
    paths: list[Path],
    *,
    semester_id: int,
    schedule_paths: list[Path] | None = None,
    preference_paths: list[Path] | None = None,
    schedule_source: SourceVersion | None = None,
    preference_source: SourceVersion | None = None,
    replace_schedule: bool = True,
    commit: bool = True,
) -> dict:
    schedule_paths = schedule_paths if schedule_paths is not None else [path for path in paths if "schedule" in path.name.casefold()]
    preference_paths = preference_paths if preference_paths is not None else [path for path in paths if "preference" in path.name.casefold()]
    if replace_schedule and len(schedule_paths) != 1:
        raise ValueError("Chọn chính xác một nguồn lịch đã được duyệt.")
    initial_issue_ids = set(db.scalars(select(ValidationIssue.id)))
    primary = schedule_paths[0] if schedule_paths else preference_paths[0]
    parsed = parse_schedule(primary) if replace_schedule else ScheduleParseResult([], [], [], 0, 0, 0)
    from sqlalchemy import func
    next_class_id = (db.scalar(select(func.max(ClassSection.id))) or 0) + 1
    for event in db.scalars(select(ImportBatch)):
        for archived in (event.summary or {}).get("groups", []):
            next_class_id = max(next_class_id, archived["id"] + 1)
    if replace_schedule:
        _clear_imported_data(db, semester_id)
    sem_obj = db.get(Semester, semester_id)
    from app.core.department_policies import resolve_or_create_department, get_department_profile_for_semester
    dept_obj = resolve_or_create_department(db, sem_obj.department_name if sem_obj else None, sem_obj.department_id if sem_obj else None)
    if sem_obj and dept_obj and not sem_obj.department_id:
        sem_obj.department_id = dept_obj.id
        db.flush()
    dept_id = sem_obj.department_id if sem_obj else (dept_obj.id if dept_obj else None)

    # Resolve all source identities before deriving any assignment/capability.
    multi_groups = set()
    parsed.issues = [i for i in parsed.issues if i.code != "MULTI_LECTURER_REVIEW"]
    for item in parsed.classes:
        if not item.lecturer_evidence:
            continue
        resolved = {}
        for row in item.lecturer_evidence:
            for identity in row["identities"]:
                lecturer, _ = resolve_identity(db, identity["name"], identity["code"], semester_id=semester_id)
                key = ("lecturer", lecturer.id) if lecturer else ("code", identity["code"]) if identity["code"] else ("name", _normalized_name(identity["name"]))
                resolved[key] = (lecturer.code, lecturer.canonical_name) if lecturer else (identity["code"], identity["name"])
        if len(resolved) > 1:
            multi_groups.add(item.key)
            item.lecturer_code = item.lecturer_name = None
        elif resolved:
            item.lecturer_code, item.lecturer_name = next(iter(resolved.values()))
    lecturers_by_name = {item.canonical_name.casefold(): item for item in db.scalars(select(Lecturer)).all()}
    lecturers_by_code = {item.code: item for item in db.scalars(select(Lecturer)).all() if item.code}
    lecturers_by_alias = {
        alias.casefold(): item
        for item in lecturers_by_name.values()
        if item.confirmed
        for alias in (item.aliases or [])
    }
    lecturers_by_normalized_name: dict[str, list[Lecturer]] = defaultdict(list)
    for lecturer in lecturers_by_name.values():
        lecturers_by_normalized_name[_normalized_name(lecturer.canonical_name)].append(lecturer)

    def ensure_lecturer(code: str | None, name: str, alias: str | None = None) -> Lecturer:
        lookup = lecturers_by_code.get(code) if code else None
        if not code:
            lookup = lookup or lecturers_by_name.get(name.casefold())
        if lookup:
            aliases = set(lookup.aliases or [])
            if alias:
                aliases.add(alias)
            lookup.aliases = sorted(aliases)
            if not lookup.department_id and dept_id:
                lookup.department_id = dept_id
            return lookup
        lecturer = Lecturer(
            code=code,
            canonical_name=name,
            department_id=dept_id,
            aliases=[alias] if alias and alias.casefold() != name.casefold() else [],
            confirmed=bool(code),
            source_file=primary.name,
        )
        db.add(lecturer)
        db.flush()
        lecturers_by_name[name.casefold()] = lecturer
        lecturers_by_normalized_name[_normalized_name(name)].append(lecturer)
        for item_alias in lecturer.aliases or []:
            lecturers_by_alias[item_alias.casefold()] = lecturer
        if code:
            lecturers_by_code[code] = lecturer
        return lecturer

    for item in parsed.classes:
        if item.lecturer_name:
            ensure_lecturer(item.lecturer_code, item.lecturer_name)

    summary = _summary(parsed)
    batch_id = (schedule_source or preference_source).import_batch_id if (schedule_source or preference_source) else None
    batch = db.get(ImportBatch, batch_id) if batch_id else None
    if batch is None:
        batch = ImportBatch(semester_id=semester_id, source_files=[path.name for path in paths], summary={})
        db.add(batch)
        db.flush()

    unmatched = set()
    existing_drafts = {
        (item.source_file, item.source_sheet, item.source_cell): item
        for item in db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id == semester_id, NormalizedPreferenceDraft.source_version_id == (preference_source.id if preference_source else None)))
    }
    protected_draft_keys=set(existing_drafts)
    preference_stats = {
        "format": None, "parsed_rules": 0, "shared_seminars": 0, "needs_review": 0,
        "invalid_rows": 0, "raw_clauses": 0, "dropped_clauses": 0,
        "warnings": [],
    }
    for preference_path in preference_paths:
        parsed_preferences = _parse_preference_source(preference_path, db.get(Semester, semester_id))
        preference_stats["format"] = parsed_preferences.format
        preference_stats["parsed_rules"] += len(parsed_preferences.drafts)
        preference_stats["shared_seminars"] += len(parsed_preferences.seminars)
        preference_stats["invalid_rows"] += parsed_preferences.invalid_rows
        preference_stats["raw_clauses"] += parsed_preferences.raw_clauses
        preference_stats["dropped_clauses"] += parsed_preferences.dropped_clauses
        preference_stats['warnings'].extend(parsed_preferences.warnings)

        profile = get_department_profile_for_semester(db, sem_obj)
        policy_cfg = profile.policy_config if profile and profile.policy_config else {}
        if parsed_preferences.format == "GRID_V3":
            # Profile-configured seed roster for legacy grid templates
            roster = policy_cfg.get("default_roster", [])
            for r_code, r_name in roster:
                ensure_lecturer(r_code, r_name)


        for preference in parsed_preferences.drafts:
            lecturer, identity_status = resolve_identity(db, preference.lecturer_alias, preference.lecturer_code, semester_id=semester_id)
            if not lecturer and preference.lecturer_code and not preference.target.get('identity_uncertain'):
                lecturer = ensure_lecturer(preference.lecturer_code, preference.canonical_name or preference.lecturer_alias, preference.lecturer_alias)
                identity_status = "EXACT_CODE"
            if preference.target.get('identity_uncertain') and identity_status!='HUMAN_CONFIRMED':
                lecturer,identity_status=None,'UNRESOLVED'
            source_snapshot={
                'raw_text':preference.raw_text,'lecturer_alias':preference.lecturer_alias,'lecturer_code':preference.lecturer_code,
                'target':{k:v for k,v in preference.target.items() if k!='_provenance'},
                'constraint_type':preference.constraint_type,'context_type':preference.context_type,
                'hardness':preference.hardness,'weight':preference.weight,
            }
            if (preference_path.name, preference.source_sheet, preference.source_cell) in protected_draft_keys:
                existing=existing_drafts[(preference_path.name,preference.source_sheet,preference.source_cell)]
                previous_source=(existing.target or {}).get('_source_snapshot')
                source_changed=previous_source!=source_snapshot if previous_source is not None else (existing.raw_text!=preference.raw_text or existing.lecturer_alias!=preference.lecturer_alias or existing.lecturer_code!=preference.lecturer_code)
                if source_changed:
                    existing.target={**(existing.target or {}),'_source_update':source_snapshot}
                    preference_stats['warnings'].append({'code':'SOURCE_CHANGED_REVIEW_REQUIRED','draft_id':existing.id,'message':'Nguồn đã thay đổi; giữ bản đã rà soát và yêu cầu đối chiếu trước khi thay thế.'})
                if existing.status!='REJECTED' and (existing.lecturer_id is None or (source_changed and lecturer is None)):
                    alias=preference.lecturer_alias
                    if alias not in unmatched:
                        unmatched.add(alias)
                        db.add(ValidationIssue(semester_id=semester_id,severity='error',code='LECTURER_IDENTITY_AMBIGUOUS',message=f"Danh tính trong nguồn '{alias}' cần rà soát.",raw_value=alias,source_file=preference_path.name,source_sheet=preference.source_sheet,source_row=preference.source_row,field=preference.source_cell))
                continue
            if lecturer:
                aliases = set(lecturer.aliases or [])
                aliases.add(preference.lecturer_alias)
                lecturer.aliases = sorted(aliases)
                if lecturer.confirmed:
                    lecturers_by_alias[preference.lecturer_alias.casefold()] = lecturer
            else:
                first_unmatched = preference.lecturer_alias not in unmatched
                unmatched.add(preference.lecturer_alias)
                if first_unmatched:
                    db.add(ValidationIssue(
                        semester_id=semester_id, severity="error", code="LECTURER_IDENTITY_AMBIGUOUS",
                        message=f"Không xác định chắc chắn giảng viên cho '{preference.lecturer_alias}'.",
                        source_file=preference_path.name, source_sheet=preference.source_sheet,
                        source_row=preference.source_row, field=preference.source_cell,
                        raw_value=preference.lecturer_alias,
                        suggestion="Xác nhận mã hoặc tên đầy đủ trước khi áp dụng nguyện vọng.",
                    ))
            needs_review = preference.needs_review or lecturer is None
            preference_stats["needs_review"] += int(needs_review)
            candidate=NormalizedPreferenceDraft(
                semester_id=semester_id, import_batch_id=batch.id, source_version_id=preference_source.id if preference_source else None,
                lecturer_id=lecturer.id if lecturer else None, lecturer_code=preference.lecturer_code,
                lecturer_alias=preference.lecturer_alias, draft_kind="CONSTRAINT",
                context_type=preference.context_type, context_confidence=preference.context_confidence,
                context_confirmed=preference.context_confirmed,
                constraint_type=preference.constraint_type, day_scope=preference.day_scope,
                periods=preference.target.get("periods", []), start_date=preference.start_date,
                end_date=preference.end_date, hardness=preference.hardness, weight=preference.weight,
                numeric_value=preference.numeric_value, target=preference.target,
                source_file=preference_path.name, source_sheet=preference.source_sheet,
                source_row=preference.source_row, source_cell=preference.source_cell,
                raw_text=preference.raw_text, confidence=preference.confidence_label if lecturer else 'LOW',
                needs_review=needs_review,
                review_reason=("Chưa xác định được giảng viên. " if lecturer is None else "") + (preference.review_reason or ""),
                status="NEEDS_REVIEW" if needs_review else preference.status,
            )
            origins=dict((candidate.target or {}).get('_provenance',{}))
            origins['lecturer_id']={'origin':('HUMAN_CONFIRMED' if identity_status in {'HUMAN_CONFIRMED','CONFIRMED_ALIAS'} else 'SOURCE_INFERRED_DETERMINISTIC') if lecturer else 'UNKNOWN','resolution':identity_status}
            candidate.target={**candidate.target,'_provenance':origins,'_source_snapshot':source_snapshot}
            if identity_status=='HUMAN_CONFIRMED': candidate.target={**candidate.target,'identity_confirmed':True}
            from app.services.preference_validation import validate_preference_draft
            provenance_only = candidate.constraint_type == "RAW_NOTE" and candidate.status == "INTERPRETED"
            validation=({"is_confirmable": False, "validation_errors": [], "validation_warnings": []}
                        if provenance_only else validate_preference_draft(candidate,db))
            if not provenance_only and not validation['is_confirmable']:
                candidate.needs_review=True
                if candidate.status!='REJECTED': candidate.status='NEEDS_REVIEW'
                candidate.confidence='LOW'
            db.add(candidate)
        for seminar in parsed_preferences.seminars:
            if (preference_path.name, seminar.source_sheet, seminar.source_cell) in protected_draft_keys:
                continue
            member_ids = []
            missing_codes = []
            for code in seminar.participant_codes:
                lecturer = lecturers_by_code.get(code) or lecturers_by_alias.get(code.casefold())
                exact_name_matches = lecturers_by_normalized_name.get(_normalized_name(code), [])
                lecturer = lecturer or (exact_name_matches[0] if len(exact_name_matches) == 1 else None)
                if lecturer:
                    member_ids.append(lecturer.id)
                else:
                    missing_codes.append(code)
            needs_review = seminar.needs_review or bool(missing_codes)
            preference_stats["needs_review"] += int(needs_review)
            db.add(NormalizedPreferenceDraft(
                semester_id=semester_id, import_batch_id=batch.id, source_version_id=preference_source.id if preference_source else None, draft_kind="SHARED_SEMINAR",
                context_type="SEMINAR", context_confidence="HIGH", context_confirmed=False,
                constraint_type="SHARED_SEMINAR", participant_codes=seminar.participant_codes,
                target={"name": seminar.name, "seminar_code": seminar.seminar_code,
                        "member_ids": member_ids, "day_scopes": seminar.day_scopes,
                        "period_blocks": seminar.period_blocks},
                hardness=seminar.hardness, weight=seminar.weight, source_file=preference_path.name,
                source_sheet=seminar.source_sheet, source_row=seminar.source_row,
                source_cell=seminar.source_cell, raw_text=seminar.raw_text, confidence="LOW" if needs_review else "HIGH",
                needs_review=needs_review,
                review_reason=seminar.review_reason or (f"Không tìm thấy mã GV: {', '.join(missing_codes)}" if missing_codes else None),
                status="NEEDS_REVIEW" if needs_review else seminar.status,
            ))

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
            id=next_class_id,
            semester_id=semester_id,
            source_version_id=schedule_source.id if schedule_source else None,
            course_id=course.id,
            class_code=item.class_code,
            credits=item.credits,
            merged_group_id=item.merged_group_id,
            merge_status="candidate" if item.merged_group_id else "single",
            # A name imported from a workbook is provenance, not an implicit
            # permanent lock.  The manager explicitly locks confirmed LOPNV
            # assignments in the workspace.
            locked_assignment=False,
            assigned_lecturer_id=lecturer.id if lecturer else None,
            assignment_source="IMPORT" if lecturer else None,
            source_file=item.source_file,
            source_sheet=item.source_sheet,
            source_row=item.source_row,
            raw_values=item.raw_values,
        )
        next_class_id += 1
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
                    confirmed=True,
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
                    source_version_id=schedule_source.id if schedule_source else None,
                    source_rows=session.source_rows or [session.source_row],
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

        if item.key in multi_groups:
            db.flush()
            meetings = db.scalars(select(ClassSession).where(ClassSession.class_id == section.id)).all()
            db.add(ValidationIssue(
                semester_id=semester_id, source_version_id=schedule_source.id if schedule_source else None,
                severity="error", code="MULTI_LECTURER_REVIEW", resolution_status="OPEN",
                message=f"{item.class_code}: cần xác nhận danh tính giảng viên cho cả TeachingGroup.",
                source_file=item.source_file, source_sheet=item.source_sheet, source_row=item.source_row,
                field="Giảng viên", raw_value="\n".join(row["raw"] for row in item.lecturer_evidence),
                details={"class_id": section.id, "class_code": section.class_code,
                         "meeting_ids": [m.id for m in meetings], "source_version_id": schedule_source.id if schedule_source else None,
                         "source_sheet": item.source_sheet, "rows": item.lecturer_evidence,
                         "resolution_status": "OPEN"},
            ))

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
                source_version_id=schedule_source.id if schedule_source else None,
            )
        )

    db.flush()
    preference_stats['needs_review']=sum(d.needs_review for d in db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id==semester_id,NormalizedPreferenceDraft.status!='REJECTED')))
    for warning in preference_stats['warnings']:
        db.add(ValidationIssue(semester_id=semester_id,severity='warning',code=warning['code'],message=warning['message'],source_sheet=warning.get('source_sheet')))
    summary["preferences"] = preference_stats
    batch.summary = summary
    db.flush()
    # Department profile-based baseline capabilities
    profile = get_department_profile_for_semester(db, sem_obj)
    policy_cfg = profile.policy_config if profile and profile.policy_config else {}
    baseline_codes = policy_cfg.get("baseline_course_codes", [])

    if baseline_codes:
        active_lecturers = db.scalars(
            select(Lecturer).where(
                Lecturer.status == "ACTIVE",
                Lecturer.confirmed.is_(True),
                or_(Lecturer.department_id == dept_id, Lecturer.department_id.is_(None)) if dept_id else True,
            )
        ).all()
        core_courses = db.scalars(select(Course).where(Course.code.in_(baseline_codes))).all()
        for lec in active_lecturers:
            has_any_cap = db.scalar(select(LecturerCourseCapability).where(
                LecturerCourseCapability.lecturer_id == lec.id,
                LecturerCourseCapability.allowed.is_(True),
                LecturerCourseCapability.confirmed.is_(True),
            ))
            if not has_any_cap and core_courses:
                for course in core_courses:
                    db.add(LecturerCourseCapability(
                        lecturer_id=lec.id,
                        course_id=course.id,
                        department_id=dept_id,
                        allowed=True,
                        confirmed=True,
                        source="DEPARTMENT_BASELINE",
                    ))

    special_caps = policy_cfg.get("special_capabilities", [])
    for item in special_caps:
        c_code = item.get("course_code")
        l_codes = set(item.get("lecturer_codes", []))
        name_sub = item.get("name_contains", "").casefold()
        target_course = db.scalar(select(Course).where(Course.code == c_code))
        if target_course:
            for lec in db.scalars(select(Lecturer).where(
                Lecturer.status == "ACTIVE",
                or_(Lecturer.department_id == dept_id, Lecturer.department_id.is_(None)) if dept_id else True,
            )).all():
                match = (lec.code in l_codes) or (name_sub and name_sub in lec.canonical_name.casefold())
                if match:
                    exists = db.scalar(select(LecturerCourseCapability).where(
                        LecturerCourseCapability.lecturer_id == lec.id,
                        LecturerCourseCapability.course_id == target_course.id,
                    ))
                    if not exists:
                        db.add(LecturerCourseCapability(
                            lecturer_id=lec.id,
                            course_id=target_course.id,
                            department_id=dept_id,
                            allowed=True,
                            confirmed=True,
                            source="DEPARTMENT_BASELINE",
                        ))
    db.flush()

    if commit:
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


def _import_files_impl(*args, **kwargs):
    try:
        return _materialize_impl(*args, **kwargs)
    except Exception:
        args[0].rollback()
        raise


def import_files(db: Session, paths: list[Path], *, semester_id: int,
                 schedule_paths=None, preference_paths=None) -> dict:
    """Stage explicitly classified files. Never activate from import order."""
    from app.services.source_authority import stage_source, source_payload
    if schedule_paths is None or preference_paths is None:
        raise ValueError("EXPLICIT_SOURCE_ROLE_REQUIRED")
    if set(paths) != set(schedule_paths) | set(preference_paths) or set(schedule_paths) & set(preference_paths):
        raise ValueError("EXPLICIT_SOURCE_ROLE_REQUIRED")
    try:
        sources = [stage_source(db, p, semester_id, role) for role, files in
                   [("CURRENT_SCHEDULE", schedule_paths), ("PREFERENCE", preference_paths)] for p in files]
        db.commit()
        return {"status": "STAGED", "sources": [source_payload(s, db.get(Semester, semester_id)) for s in sources]}
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
        "partial_merge_candidates": len(parsed.partial_merge_candidates),
        "locked_classes": sum(1 for item in parsed.classes if item.locked_assignment),
        "unassigned_classes": sum(1 for item in parsed.classes if not item.locked_assignment),
        "validation_errors": sum(1 for issue in parsed.issues if issue.severity == "error"),
    }


def dashboard(db: Session, semester_id: int, run_id: int | None = None) -> dict:
    classes = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    issues = db.scalars(select(ValidationIssue).where(
        ValidationIssue.semester_id == semester_id,
        ValidationIssue.resolution_status != "SUPERSEDED",
    )).all()
    lecturers = db.scalars(select(Lecturer)).all()
    
    from app.models.entities import Assignment, OptimizationRun
    from app.services.source_authority import latest_current_run

    run = None
    if run_id is not None:
        run = db.get(OptimizationRun, run_id)
        if run and run.semester_id != semester_id:
            run = None
    if not run and run_id is None:
        run = latest_current_run(db, semester_id)

    if run and run.status in {"optimal", "feasible"}:
        assigned_ids = set(
            db.scalars(select(Assignment.class_id).where(Assignment.run_id == run.id)).all()
        )
        unassigned_classes = len([item for item in classes if item.id not in assigned_ids])
    else:
        unassigned_classes = sum(item.assigned_lecturer_id is None for item in classes)
        
    from app.services.unassigned_diagnostics import get_unassigned_breakdown
    breakdown = get_unassigned_breakdown(db, semester_id, run.id if run else None)

    return {
        "classes": len(classes),
        "locked_classes": sum(item.locked_assignment for item in classes),
        "unassigned_classes": unassigned_classes,
        "unassigned_breakdown": breakdown,
        "merged_suggestions": len({item.merged_group_id for item in classes if item.merged_group_id}),
        "lecturers": len(lecturers),
        "validation_errors": sum(issue.severity == "error" for issue in issues),
        "issues_count": len(issues),
        "optimization_status": run.status if run else "not_run",
        "optimization_score": run.score if run else None,
    }

