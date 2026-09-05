from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import Assignment, ClassSection, LecturerCourseCapability, OptimizationRun
from app.optimization.solver import _overlap

def capability_readiness(db: Session, semester_id: int) -> dict:
    groups=db.scalars(select(ClassSection).where(ClassSection.semester_id==semester_id)).all()
    caps=db.scalars(select(LecturerCourseCapability)).all(); by_course=defaultdict(list)
    for cap in caps: by_course[cap.course_id].append(cap)
    eligible=sum(any(c.allowed and c.confirmed for c in by_course[g.course_id]) for g in groups)
    return {"total_teaching_groups":len(groups),"locked_imported":sum(g.locked_assignment for g in groups),"needs_solver":sum(not g.locked_assignment for g in groups),"eligible_groups":eligible,"no_eligible_lecturer":len(groups)-eligible,"confirmed_capabilities":sum(c.confirmed and c.allowed for c in caps),"unconfirmed_capabilities":sum(not c.confirmed for c in caps),"code":"CAPABILITY_DATA_INCOMPLETE" if eligible < len(groups) else None}

def validate_schedule(db: Session, semester_id: int, run_id: int) -> dict:
    run=db.get(OptimizationRun,run_id)
    if not run or run.semester_id!=semester_id: raise ValueError("Run không thuộc kỳ học.")
    assignments=db.scalars(select(Assignment).options(selectinload(Assignment.class_section).selectinload(ClassSection.sessions)).where(Assignment.run_id==run_id)).all()
    caps={(c.lecturer_id,c.course_id) for c in db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.allowed.is_(True),LecturerCourseCapability.confirmed.is_(True)))}
    errors=[]
    for item in assignments:
        if (item.lecturer_id,item.class_section.course_id) not in caps: errors.append({"code":"COURSE_CAPABILITY_MISSING","class_id":item.class_id})
    for i,left in enumerate(assignments):
        for right in assignments[i+1:]:
            if left.lecturer_id==right.lecturer_id and any(_overlap(a,b) for a in left.class_section.sessions for b in right.class_section.sessions): errors.append({"code":"TIMETABLE_CONFLICT","class_id":left.class_id})
    return {"valid":not errors,"blocking_errors":errors,"warnings":[],"counts":{"assignments":len(assignments),"hard_violations":len(errors)}}
