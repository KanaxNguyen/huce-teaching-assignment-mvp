from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import ClassSection, Constraint, Lecturer, LecturerCourseCapability, Semester, Seminar, Course, DepartmentProfile
from app.optimization.solver import _overlap, _slot_match, _normalized_type, _event_slots
from app.optimization.occurrences import confirmed_merge, meeting_occurrences
from app.services.assignment_state import assignment_state, save_manual_version
from app.models.entities import LecturerSemesterProfile

def assignment_check_context(db: Session, semester_id: int, run=None) -> dict:
    """Load one request-scoped snapshot for all candidate checks; never cache across edits."""
    from app.services.source_authority import active_issues, latest_current_run
    semester = db.get(Semester, semester_id)
    if semester is None:
        return {"groups": {}, "lecturers": {}}
    run = run or latest_current_run(db, semester_id)
    groups = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions),
        selectinload(ClassSection.course)).where(ClassSection.semester_id == semester_id)).all()
    profiles = {p.lecturer_id: p for p in db.scalars(select(LecturerSemesterProfile).where(
        LecturerSemesterProfile.semester_id == semester_id))}
    return dict(semester=semester, run=run, groups={g.id: g for g in groups},
        lecturers={l.id: l for l in db.scalars(select(Lecturer))}, profiles=profiles,
        policy=db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == semester.department_id)) if semester.department_id else None,
        courses=list(db.scalars(select(Course))), caps=list(db.scalars(select(LecturerCourseCapability))),
        constraints=list(db.scalars(select(Constraint).where(Constraint.semester_id == semester_id,
            Constraint.active.is_(True), Constraint.confirmed.is_(True)))),
        issues=active_issues(db, semester_id), seminars=list(db.scalars(select(Seminar).where(Seminar.semester_id == semester_id))),
        state=assignment_state(db, semester_id, run))


def check_assignment_change(db: Session, semester_id: int, class_id: int, lecturer_id: int, *, context=None) -> dict:
    context = context or assignment_check_context(db, semester_id)
    group = context['groups'].get(class_id)
    lecturer = context['lecturers'].get(lecturer_id); reasons=[]; affected=[]
    if not group: reasons.append("TEACHING_GROUP_NOT_FOUND")
    if not lecturer: reasons.append("LECTURER_NOT_FOUND")
    if reasons: return {"valid":False,"blocking_reasons":reasons,"warnings":[],"affected_groups":[]}
    for issue in context['issues']:
        if issue.code in {"MULTI_LECTURER_REVIEW", "SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT"} and issue.details.get('class_id') == class_id:
            reasons.append(issue.code)
    profile = context['profiles'].get(lecturer_id)
    if lecturer.status != 'ACTIVE': reasons.append('LECTURER_INACTIVE')
    elif profile and profile.participation_status != 'ACTIVE': reasons.append('LECTURER_NOT_PARTICIPATING')
    semester, policy = context['semester'], context['policy']
    from app.services.capability_resolution import _plain_text
    equivalent_ids = {c.id for c in context['courses']
                      if len(_plain_text(group.course.name)) >= 3 and _plain_text(c.name) == _plain_text(group.course.name)}
    equivalent_ids.add(group.course_id)
    caps = [c for c in context['caps'] if c.lecturer_id == lecturer_id]
    forbidden = any(c.course_id == group.course_id and not c.allowed for c in caps)
    eligible = any(c.course_id in equivalent_ids and c.allowed and c.source != "HYPOTHETICAL_ALL" and
                   (c.confirmed or (policy and policy.allow_provisional_capability)) and
                   (semester.department_id is None or c.department_id in {None, semester.department_id}) for c in caps)
    if forbidden or not eligible: reasons.append("COURSE_CAPABILITY_MISSING")
    if semester.department_id and lecturer.department_id not in {None, semester.department_id}:
        reasons.append("LECTURER_DEPARTMENT_MISMATCH")
    lecturer_constraints = [c for c in context['constraints'] if c.lecturer_id == lecturer_id]
    for c in lecturer_constraints:
        target=c.target or {}; kind=_normalized_type(c.constraint_type)
        if c.hardness != "hard":
            continue
        if kind == "FORBIDDEN_ASSIGNMENT" and (target.get("class_id") == class_id or target.get("course_id") == group.course_id or target.get("course_code") == group.course.code): reasons.append("FORBIDDEN_ASSIGNMENT")
        matches = [_slot_match(s, target, semester) for s in group.sessions]
        if kind in {"AVOID_DAYS", "PREFERRED_DAYS"}:
            matches = [s.weekday in (target.get("weekdays") or []) for s in group.sessions]
        if kind in {"UNAVAILABLE", "BUSY_EVENT", "AVOID_PERIOD", "AVOID_DAYS"} and any(matches): reasons.append("HARD_AVAILABILITY_CONFLICT")
        if kind in {"PREFERRED", "PREFERRED_DAYS"} and not all(matches): reasons.append("HARD_PREFERENCE_CONFLICT")
    for constraint in context['constraints']:
        if _normalized_type(constraint.constraint_type) == 'REQUIRED_ASSIGNMENT' and constraint.hardness == "hard" and constraint.target.get("class_id") == class_id and constraint.lecturer_id != lecturer_id:
            reasons.append("REQUIRED_ASSIGNMENT_CONFLICT")
    state = context['state']
    assigned = [g for cid,g in context['groups'].items() if cid != class_id and state.get(cid,(None,))[0] == lecturer_id]
    overlapping_details = []
    for other in assigned:
        if confirmed_merge(group, other):
            continue
        for a in group.sessions:
            for b in other.sessions:
                if _overlap(a, b, semester):
                    reasons.append("TIMETABLE_CONFLICT")
                    affected.append(other.id)
                    overlapping_details.append({
                        "class_id": other.id,
                        "class_code": other.class_code,
                        "course_name": other.course.name if other.course else "",
                        "weekday": b.weekday,
                        "periods": f"{b.start_period}–{b.end_period}",
                        "overlapping_weeks": sorted(set(a.active_weeks).intersection(b.active_weeks)),
                    })
    # A manual edit keeps the currently selected shared seminar slot. Without a
    # solved slot, it must leave at least one alternative feasible for all members.
    run = context["run"]
    selected = {s["id"]: s.get("slot") for s in (run.summary or {}).get("seminars", [])} if run else {}
    all_groups = context["groups"].values()
    for seminar in context["seminars"]:
        if seminar.hardness != "hard" or lecturer_id not in (seminar.members or []):
            continue
        slots = [selected[seminar.id]] if selected.get(seminar.id) else _event_slots(seminar)
        member_groups = [g for g in all_groups if g.id != class_id and state.get(g.id, (None,))[0] in seminar.members]
        if not slots or not any(not any(_slot_match(m, slot, semester) for g in [*member_groups, group] for m in g.sessions) for slot in slots):
            reasons.append("HARD_SEMINAR_CONFLICT")
    # Count confirmed merged groups only once for workload constraints.
    workload_groups = []
    for item in [*assigned, group]:
        if not any(confirmed_merge(item, old) for old in workload_groups): workload_groups.append(item)
    for constraint in lecturer_constraints:
        if constraint.hardness != "hard":
            continue
        target = constraint.target or {}
        kind = _normalized_type(constraint.constraint_type)
        if kind == "MAX_CLASSES" and len(workload_groups) > target.get("max", float("inf")):
            reasons.append("MAX_WORKLOAD_EXCEEDED")
        elif kind == "MAX_SESSIONS_PER_DAY":
            limit = target.get("max")
            if isinstance(limit, int):
                from collections import Counter
                counts = Counter(actual for item in workload_groups for session in item.sessions
                                 for _, actual in meeting_occurrences(session, semester))
                if any(count > limit for count in counts.values()): reasons.append("MAX_WORKLOAD_EXCEEDED")
        elif kind == "MAX_DAYS_PER_WEEK":
            limit = target.get("max")
            if isinstance(limit, int):
                days = {session.weekday for item in assigned for session in item.sessions}
                days.update(session.weekday for session in group.sessions)
                if len(days) > limit: reasons.append("MAX_WORKLOAD_EXCEEDED")
        elif kind == "MAX_CONSECUTIVE_BLOCKS":
            limit = target.get("max")
            if isinstance(limit, int) and limit >= 1:
                for weekday in range(2, 9):
                    occupied = set()
                    for item in [*assigned, group]:
                        for session in item.sessions:
                            if session.weekday != weekday:
                                continue
                            for index, (start, end) in enumerate(((1, 3), (4, 6), (7, 9), (10, 12), (13, 15))):
                                if not (session.end_period < start or end < session.start_period): occupied.add(index)
                    longest = current = 0
                    for index in range(5):
                        current = current + 1 if index in occupied else 0
                        longest = max(longest, current)
                    if longest > limit: reasons.append("MAX_WORKLOAD_EXCEEDED")
    warnings = []
    if group.locked_assignment and group.assigned_lecturer_id != lecturer_id:
        warnings.append("CURRENTLY_LOCKED_TO_OTHER_LECTURER")
    return {
        "valid": not reasons,
        "blocking_reasons": sorted(set(reasons)),
        "warnings": warnings,
        "affected_groups": sorted(set(affected)),
        "overlapping_details": overlapping_details,
    }

def apply_manual_assignment(
    db: Session,
    semester_id: int,
    class_id: int,
    lecturer_id: int,
    lock: bool = False,
    allow_override_lock: bool = False,
    override_reason: str = "",
    user: str = "Human Operator",
) -> dict:
    group = db.get(ClassSection, class_id)
    if not group or group.semester_id != semester_id:
        return {"valid": False, "blocking_reasons": ["TEACHING_GROUP_NOT_FOUND"], "warnings": [], "affected_groups": []}

    if group.locked_assignment and group.assigned_lecturer_id != lecturer_id and not allow_override_lock:
        return {
            "valid": False,
            "blocking_reasons": ["LOCKED_ASSIGNMENT_REQUIRES_OVERRIDE"],
            "warnings": ["Lớp hiện đang bị khóa. Yêu cầu xác nhận mở khóa có kiểm toán."],
            "affected_groups": [class_id],
            "current_locked_lecturer_id": group.assigned_lecturer_id,
        }

    result = check_assignment_change(db, semester_id, class_id, lecturer_id)
    if not result["valid"]:
        return result

    previous_lecturer_id = group.assigned_lecturer_id
    was_locked = group.locked_assignment

    if was_locked and previous_lecturer_id != lecturer_id:
        from app.models.entities import ValidationIssue
        audit = ValidationIssue(
            semester_id=semester_id,
            severity="info",
            code="MANUAL_LOCK_OVERRIDE",
            message=f"Ghi đè phân công đã khóa cho lớp {group.class_code}: {override_reason or 'Phân công ghi đè thủ công'} (Bởi: {user})",
            details={
                "class_id": class_id,
                "previous_lecturer_id": previous_lecturer_id,
                "new_lecturer_id": lecturer_id,
                "was_locked": was_locked,
                "reason": override_reason or "Phân công ghi đè thủ công",
                "performed_by": user,
            },
            resolution_status="RESOLVED",
        )
        db.add(audit)
        group.assignment_source = "MANUAL_OVERRIDE"
    else:
        group.assignment_source = "MANUAL"

    group.assigned_lecturer_id = lecturer_id
    group.locked_assignment = lock
    try:
        changes = {group.id: (lecturer_id, group.assignment_source, lock)}
        peers = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
        for peer in peers:
            if peer.id != group.id and confirmed_merge(group, peer):
                if peer.locked_assignment and peer.assigned_lecturer_id != lecturer_id:
                    db.rollback()
                    return {"valid": False, "blocking_reasons": ["MERGED_LOCK_CONFLICT"], "warnings": [], "affected_groups": [peer.id]}
                peer.assigned_lecturer_id = lecturer_id
                peer.assignment_source = group.assignment_source
                changes[peer.id] = (lecturer_id, peer.assignment_source, peer.locked_assignment)
        save_manual_version(db, semester_id, changes)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result, "assignment_source": group.assignment_source, "locked": lock}


def confirm_source_merges(db: Session, semester_id: int) -> list[str]:
    """Confirm suggested merges that the source file itself already teaches as one class.

    A group qualifies only when every member came from the import with the same
    lecturer and the members share an identical schedule; partial overlaps stay
    unconfirmed (meeting-level merge is deferred). Called only from an explicit
    user lock action, never from a solver run.
    """
    from app.optimization.occurrences import are_classes_mergeable
    members: dict[str, list[ClassSection]] = {}
    for group in db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(
            ClassSection.semester_id == semester_id, ClassSection.merged_group_id.is_not(None))):
        members.setdefault(group.merged_group_id, []).append(group)
    confirmed = []
    for group_id, items in sorted(members.items()):
        if len(items) < 2 or any(item.merge_status != "candidate" for item in items):
            continue
        lecturers = {item.assigned_lecturer_id for item in items}
        if None in lecturers or len(lecturers) != 1 or any(item.assignment_source != "IMPORT" for item in items):
            continue
        if not all(are_classes_mergeable(items[0], other) for other in items[1:]):
            continue
        for item in items:
            item.merged_confirmed = True
            item.merge_status = "confirmed"
        confirmed.append(group_id)
    # The parser never suggests a merge when a meeting has a blank room (e.g. a
    # make-up session or an export without rooms). One lecturer cannot teach two
    # separate classes at once, so when the source gives the same lecturer,
    # identical meetings with the same rooms (blank matching blank) are enough.
    def signature(group):
        return tuple(sorted((s.weekday, s.start_period, s.end_period, s.room.strip(), tuple(s.active_weeks or []),
                             s.start_date, s.end_date) for s in group.sessions))
    singles: dict[tuple, list[ClassSection]] = {}
    for group in db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(
            ClassSection.semester_id == semester_id, ClassSection.merged_group_id.is_(None),
            ClassSection.assignment_source == "IMPORT", ClassSection.assigned_lecturer_id.is_not(None))):
        if group.sessions:
            singles.setdefault((group.course_id, group.assigned_lecturer_id, signature(group)), []).append(group)
    for items in singles.values():
        if len(items) < 2 or not all(are_classes_mergeable(items[0], other) for other in items[1:]):
            continue
        group_id = f"MG-S{min(item.id for item in items):04d}"
        for item in items:
            item.merged_group_id = group_id
            item.merged_confirmed = True
            item.merge_status = "confirmed"
        confirmed.append(group_id)
    db.flush()
    return confirmed


def lock_assigned_classes(db: Session, semester_id: int) -> dict:
    """Lock every currently assigned, unlocked class that passes the manual checker.

    Assignment source is left untouched: source and lock are independent attributes.
    All valid locks are saved as one manual version so run history is not flooded.
    """
    from app.services.assignment_state import assignment_state, save_manual_version
    merges = confirm_source_merges(db, semester_id)
    state = assignment_state(db, semester_id)
    locked, skipped, changes = [], [], {}
    for class_id, (lecturer_id, source, already_locked) in sorted(state.items()):
        group = db.get(ClassSection, class_id)
        if not group or group.semester_id != semester_id or lecturer_id is None or already_locked:
            continue
        result = check_assignment_change(db, semester_id, class_id, lecturer_id)
        if not result["valid"]:
            skipped.append({"class_id": class_id, "class_code": group.class_code, "blocking_reasons": result["blocking_reasons"]})
            continue
        changes[class_id] = (lecturer_id, source, True)
        locked.append(class_id)
    try:
        for class_id in locked:
            group = db.get(ClassSection, class_id)
            group.assigned_lecturer_id = changes[class_id][0]
            group.locked_assignment = True
        if changes:
            save_manual_version(db, semester_id, changes)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"locked": len(locked), "skipped": skipped, "confirmed_merges": merges}
