from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import ClassSection, Constraint, Lecturer, LecturerCourseCapability
from app.optimization.solver import _overlap, _slot_match

def check_assignment_change(db: Session, semester_id: int, class_id: int, lecturer_id: int) -> dict:
    group = db.scalar(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.id == class_id, ClassSection.semester_id == semester_id))
    lecturer = db.get(Lecturer, lecturer_id); reasons=[]; affected=[]
    if not group: reasons.append("TEACHING_GROUP_NOT_FOUND")
    if not lecturer: reasons.append("LECTURER_NOT_FOUND")
    if reasons: return {"valid":False,"blocking_reasons":reasons,"warnings":[],"affected_groups":[]}
    cap = db.scalar(select(LecturerCourseCapability).where(LecturerCourseCapability.lecturer_id==lecturer_id, LecturerCourseCapability.course_id==group.course_id, LecturerCourseCapability.allowed.is_(True), LecturerCourseCapability.confirmed.is_(True)))
    if not cap: reasons.append("COURSE_CAPABILITY_MISSING")
    lecturer_constraints = db.scalars(select(Constraint).where(Constraint.semester_id==semester_id, Constraint.lecturer_id==lecturer_id, Constraint.active.is_(True), Constraint.confirmed.is_(True))).all()
    for c in lecturer_constraints:
        target=c.target or {}; kind=c.constraint_type.lower()
        if c.hardness != "hard":
            continue
        if kind in {"forbidden_assignment","forbidden"} and (target.get("class_id") == class_id or target.get("course_id") == group.course_id): reasons.append("FORBIDDEN_ASSIGNMENT")
        if kind in {"unavailable","busy_event"} and any(_slot_match(s, target) for s in group.sessions): reasons.append("HARD_AVAILABILITY_CONFLICT")
    for constraint in db.scalars(select(Constraint).where(
        Constraint.semester_id == semester_id,
        Constraint.active.is_(True),
        Constraint.confirmed.is_(True),
        Constraint.constraint_type.in_(["REQUIRED_ASSIGNMENT", "required_assignment"]),
    )).all():
        if constraint.hardness == "hard" and constraint.target.get("class_id") == class_id and constraint.lecturer_id != lecturer_id:
            reasons.append("REQUIRED_ASSIGNMENT_CONFLICT")
    assigned = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id==semester_id, ClassSection.assigned_lecturer_id==lecturer_id, ClassSection.id!=class_id)).all()
    for other in assigned:
        if any(_overlap(a,b) for a in group.sessions for b in other.sessions): reasons.append("TIMETABLE_CONFLICT"); affected.append(other.id)
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
                            for index, (start, end) in enumerate(((1, 3), (4, 6), (7, 9), (10, 12))):
                                if not (session.end_period < start or end < session.start_period): occupied.add(index)
                    longest = current = 0
                    for index in range(4):
                        current = current + 1 if index in occupied else 0
                        longest = max(longest, current)
                    if longest > limit: reasons.append("MAX_WORKLOAD_EXCEEDED")
    return {"valid":not reasons,"blocking_reasons":sorted(set(reasons)),"warnings":[],"affected_groups":affected}

def apply_manual_assignment(db: Session, semester_id: int, class_id: int, lecturer_id: int, lock: bool=False) -> dict:
    result=check_assignment_change(db,semester_id,class_id,lecturer_id)
    if not result["valid"]: return result
    group=db.get(ClassSection,class_id); group.assigned_lecturer_id=lecturer_id; group.assignment_source="MANUAL"; group.locked_assignment=lock
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result,"assignment_source":"MANUAL","locked":lock}
