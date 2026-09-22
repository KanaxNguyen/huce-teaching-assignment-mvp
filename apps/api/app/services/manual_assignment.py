from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import ClassSection, Constraint, Lecturer, LecturerCourseCapability, Semester
from app.optimization.solver import _overlap, _slot_match
from app.services.lecturer_master import participation_reason

def check_assignment_change(db: Session, semester_id: int, class_id: int, lecturer_id: int) -> dict:
    group = db.scalar(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.id == class_id, ClassSection.semester_id == semester_id))
    lecturer = db.get(Lecturer, lecturer_id); reasons=[]; affected=[]
    if not group: reasons.append("TEACHING_GROUP_NOT_FOUND")
    if not lecturer: reasons.append("LECTURER_NOT_FOUND")
    if reasons: return {"valid":False,"blocking_reasons":reasons,"warnings":[],"affected_groups":[]}
    from app.services.source_authority import active_issues
    for issue in active_issues(db, semester_id):
        if issue.code in {"MULTI_LECTURER_REVIEW", "SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT"} and issue.details.get('class_id') == class_id:
            reasons.append(issue.code)
    inactive_reason = participation_reason(db, lecturer, semester_id)
    if inactive_reason:
        reasons.append(inactive_reason)
    cap = db.scalar(select(LecturerCourseCapability).where(LecturerCourseCapability.lecturer_id==lecturer_id, LecturerCourseCapability.course_id==group.course_id, LecturerCourseCapability.allowed.is_(True), LecturerCourseCapability.confirmed.is_(True)))
    if not cap: reasons.append("COURSE_CAPABILITY_MISSING")
    lecturer_constraints = db.scalars(select(Constraint).where(Constraint.semester_id==semester_id, Constraint.lecturer_id==lecturer_id, Constraint.active.is_(True), Constraint.confirmed.is_(True))).all()
    semester = db.get(Semester, semester_id)
    for c in lecturer_constraints:
        target=c.target or {}; kind=c.constraint_type.lower()
        if c.hardness != "hard":
            continue
        if kind in {"forbidden_assignment","forbidden"} and (target.get("class_id") == class_id or target.get("course_id") == group.course_id): reasons.append("FORBIDDEN_ASSIGNMENT")
        if kind in {"unavailable","busy_event"} and any(_slot_match(s, target, semester) for s in group.sessions): reasons.append("HARD_AVAILABILITY_CONFLICT")
    for constraint in db.scalars(select(Constraint).where(
        Constraint.semester_id == semester_id,
        Constraint.active.is_(True),
        Constraint.confirmed.is_(True),
        Constraint.constraint_type.in_(["REQUIRED_ASSIGNMENT", "required_assignment"]),
    )).all():
        if constraint.hardness == "hard" and constraint.target.get("class_id") == class_id and constraint.lecturer_id != lecturer_id:
            reasons.append("REQUIRED_ASSIGNMENT_CONFLICT")
    assigned = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id==semester_id, ClassSection.assigned_lecturer_id==lecturer_id, ClassSection.id!=class_id)).all()
    overlapping_details = []
    for other in assigned:
        for a in group.sessions:
            for b in other.sessions:
                if _overlap(a, b):
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
    for constraint in lecturer_constraints:
        if constraint.hardness != "hard":
            continue
        target = constraint.target or {}
        kind = constraint.constraint_type.upper()
        if kind == "MAX_CLASSES" and len(assigned) + 1 > target.get("max", float("inf")):
            reasons.append("MAX_WORKLOAD_EXCEEDED")
        elif kind == "MAX_SESSIONS_PER_DAY":
            limit = target.get("max")
            if isinstance(limit, int):
                for weekday in range(2, 9):
                    count = sum(sum(session.weekday == weekday for session in item.sessions) for item in assigned)
                    count += sum(session.weekday == weekday for session in group.sessions)
                    if count > limit: reasons.append("MAX_WORKLOAD_EXCEEDED")
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
    if not group:
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
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result, "assignment_source": group.assignment_source, "locked": lock}

