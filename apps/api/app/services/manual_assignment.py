from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import ClassSection, Constraint, Lecturer, LecturerCourseCapability
from app.optimization.solver import _overlap

def check_assignment_change(db: Session, semester_id: int, class_id: int, lecturer_id: int) -> dict:
    group = db.scalar(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.id == class_id, ClassSection.semester_id == semester_id))
    lecturer = db.get(Lecturer, lecturer_id); reasons=[]; affected=[]
    if not group: reasons.append("TEACHING_GROUP_NOT_FOUND")
    if not lecturer: reasons.append("LECTURER_NOT_FOUND")
    if reasons: return {"valid":False,"blocking_reasons":reasons,"warnings":[],"affected_groups":[]}
    cap = db.scalar(select(LecturerCourseCapability).where(LecturerCourseCapability.lecturer_id==lecturer_id, LecturerCourseCapability.course_id==group.course_id, LecturerCourseCapability.allowed.is_(True), LecturerCourseCapability.confirmed.is_(True)))
    if not cap: reasons.append("COURSE_CAPABILITY_MISSING")
    for c in db.scalars(select(Constraint).where(Constraint.semester_id==semester_id, Constraint.lecturer_id==lecturer_id, Constraint.active.is_(True), Constraint.confirmed.is_(True))):
        target=c.target or {}; kind=c.constraint_type.lower()
        if kind in {"forbidden_assignment","forbidden"} and target.get("class_id")==class_id: reasons.append("FORBIDDEN_ASSIGNMENT")
        if kind in {"unavailable","busy_event"} and c.hardness=="hard" and any(target.get("weekday") in (None,s.weekday) and (not target.get("periods") or any(s.start_period<=p<=s.end_period for p in target["periods"])) for s in group.sessions): reasons.append("HARD_AVAILABILITY_CONFLICT")
    for other in db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id==semester_id, ClassSection.assigned_lecturer_id==lecturer_id, ClassSection.id!=class_id)):
        if any(_overlap(a,b) for a in group.sessions for b in other.sessions): reasons.append("TIMETABLE_CONFLICT"); affected.append(other.id)
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
