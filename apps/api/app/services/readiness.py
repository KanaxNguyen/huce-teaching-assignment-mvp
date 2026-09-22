from collections import defaultdict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import Assignment, ClassSection, LecturerCourseCapability, OptimizationRun
from app.optimization.solver import _overlap

def capability_readiness(db: Session, semester_id: int) -> dict:
    from app.services.capability_resolution import CapabilityResolutionService
    res = CapabilityResolutionService.evaluate_capability_readiness(db, semester_id)
    groups = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    caps = db.scalars(select(LecturerCourseCapability).where(
        or_(LecturerCourseCapability.source.is_(None), LecturerCourseCapability.source != "HYPOTHETICAL_ALL")
    )).all()
    by_course = defaultdict(list)
    for cap in caps:
        by_course[cap.course_id].append(cap)
    eligible = sum(any(c.allowed and c.confirmed for c in by_course[g.course_id]) for g in groups)

    output = {
        "total_teaching_groups": len(groups),
        "locked_imported": sum(g.locked_assignment for g in groups),
        "needs_solver": sum(not g.locked_assignment for g in groups),
        "eligible_groups": eligible,
        "no_eligible_lecturer": len(groups) - eligible,
        "confirmed_capabilities": sum(c.confirmed and c.allowed for c in caps),
        "unconfirmed_capabilities": sum(not c.confirmed for c in caps),
        "code": "CAPABILITY_DATA_INCOMPLETE" if eligible < len(groups) else None,
    }
    output.update(res)
    return output


def validate_schedule(db: Session, semester_id: int, run_id: int) -> dict:
    run = db.get(OptimizationRun, run_id)
    if not run or run.semester_id != semester_id:
        raise ValueError("Run không thuộc kỳ học.")
    from app.models.entities import ClassSession, Constraint, Course, DepartmentProfile, Lecturer, Semester
    from app.optimization.solver import _normalized_type, _slot_match

    semester = db.get(Semester, semester_id)
    policy = None
    if semester and semester.department_id:
        policy = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == semester.department_id))

    all_semester_classes = db.scalars(
        select(ClassSection).where(ClassSection.semester_id == semester_id)
    ).all()

    assignments = db.scalars(
        select(Assignment).options(
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
        ).where(Assignment.run_id == run_id)
    ).all()

    # 1. Capability authority checking
    cap_query = select(LecturerCourseCapability).where(
        or_(
            LecturerCourseCapability.source.is_(None),
            LecturerCourseCapability.source != "HYPOTHETICAL_ALL",
        )
    )
    if semester and semester.department_id:
        cap_query = cap_query.where(
            or_(
                LecturerCourseCapability.department_id == semester.department_id,
                LecturerCourseCapability.department_id.is_(None),
            )
        )
    all_caps = db.scalars(cap_query).all()
    allowed_caps = {
        (c.lecturer_id, c.course_id)
        for c in all_caps
        if c.allowed and (c.confirmed or (policy and policy.allow_provisional_capability))
    }
    forbidden_caps = {
        (c.lecturer_id, c.course_id)
        for c in all_caps
        if not c.allowed
    }

    errors: list[dict] = []
    warnings: list[dict] = []

    # Check capability violations
    for item in assignments:
        key = (item.lecturer_id, item.class_section.course_id)
        if key in forbidden_caps:
            errors.append({
                "code": "ASSIGNMENT_WITHOUT_VALID_CAPABILITY",
                "class_id": item.class_id,
                "lecturer_id": item.lecturer_id,
                "course_id": item.class_section.course_id,
                "message": f"Giảng viên {item.lecturer_id} bị cấm giảng dạy học phần {item.class_section.course_id}",
            })
            errors.append({"code": "FORBIDDEN_CAPABILITY", "class_id": item.class_id})
        elif key not in allowed_caps:
            errors.append({
                "code": "ASSIGNMENT_WITHOUT_VALID_CAPABILITY",
                "class_id": item.class_id,
                "lecturer_id": item.lecturer_id,
                "course_id": item.class_section.course_id,
                "message": f"Giảng viên {item.lecturer_id} không có năng lực giảng dạy học phần {item.class_section.course_id}",
            })
            errors.append({"code": "COURSE_CAPABILITY_MISSING", "class_id": item.class_id})

    # 2. Lecturer overlap & week-mask overlap
    for i, left in enumerate(assignments):
        for right in assignments[i + 1:]:
            if left.lecturer_id == right.lecturer_id and any(
                _overlap(a, b) for a in left.class_section.sessions for b in right.class_section.sessions
            ):
                errors.append({
                    "code": "TIMETABLE_CONFLICT",
                    "class_id": left.class_id,
                    "other_class_id": right.class_id,
                    "lecturer_id": left.lecturer_id,
                    "message": f"Xung đột lịch giữa lớp {left.class_id} và {right.class_id} của GV {left.lecturer_id}",
                })

    # 3. Locked assignment consistency
    for item in assignments:
        sec = item.class_section
        if (sec.locked_assignment or item.locked) and sec.assigned_lecturer_id is not None:
            if item.lecturer_id != sec.assigned_lecturer_id:
                errors.append({
                    "code": "LOCKED_ASSIGNMENT_INCONSISTENCY",
                    "class_id": item.class_id,
                    "expected_lecturer_id": sec.assigned_lecturer_id,
                    "actual_lecturer_id": item.lecturer_id,
                    "message": f"Lớp {item.class_id} bị khóa cho GV {sec.assigned_lecturer_id} nhưng lại được gán cho GV {item.lecturer_id}",
                })

    # 4. Constraints validation (forbidden, availability, workload limits, required)
    constraints = db.scalars(
        select(Constraint).where(
            Constraint.semester_id == semester_id,
            Constraint.active.is_(True),
            Constraint.confirmed.is_(True),
        )
    ).all()

    assigned_by_lecturer: dict[int, list[Assignment]] = defaultdict(list)
    for a in assignments:
        assigned_by_lecturer[a.lecturer_id].append(a)

    for c in constraints:
        kind = _normalized_type(c.constraint_type)
        lec_id = c.lecturer_id
        target = c.target or {}

        if kind == "FORBIDDEN_ASSIGNMENT" and lec_id:
            # Check if lecturer is assigned to forbidden class/course
            for a in assigned_by_lecturer.get(lec_id, []):
                tgt_class_id = target.get("class_id")
                tgt_course_code = target.get("course_code")
                if tgt_class_id and a.class_id == tgt_class_id:
                    errors.append({
                        "code": "FORBIDDEN_ASSIGNMENT_VIOLATION",
                        "class_id": a.class_id,
                        "lecturer_id": lec_id,
                        "message": f"GV {lec_id} bị cấm phân công lớp {a.class_id}",
                    })
                elif tgt_course_code and a.class_section.course and a.class_section.course.code == tgt_course_code:
                    errors.append({
                        "code": "FORBIDDEN_ASSIGNMENT_VIOLATION",
                        "class_id": a.class_id,
                        "lecturer_id": lec_id,
                        "message": f"GV {lec_id} bị cấm phân công môn {tgt_course_code}",
                    })

        elif kind in {"UNAVAILABLE", "BUSY_EVENT", "AVOID_PERIOD", "AVOID_DAYS"} and c.hardness == "hard" and lec_id:
            for a in assigned_by_lecturer.get(lec_id, []):
                for session in a.class_section.sessions:
                    if _slot_match(session, target, semester):
                        errors.append({
                            "code": "AVAILABILITY_VIOLATION",
                            "class_id": a.class_id,
                            "lecturer_id": lec_id,
                            "message": f"GV {lec_id} bận cứng tại khung giờ lớp {a.class_id}",
                        })

        elif kind == "MAX_CLASSES" and c.hardness == "hard" and lec_id:
            max_c = target.get("max", float("inf"))
            actual_c = len(assigned_by_lecturer.get(lec_id, []))
            if actual_c > max_c:
                errors.append({
                    "code": "MAX_CLASSES_EXCEEDED",
                    "lecturer_id": lec_id,
                    "limit": max_c,
                    "actual": actual_c,
                    "message": f"GV {lec_id} được phân {actual_c} lớp, vượt giới hạn {max_c}",
                })

        elif kind == "MAX_SESSIONS_PER_DAY" and c.hardness == "hard" and lec_id:
            max_s = target.get("max", float("inf"))
            day_counts = defaultdict(int)
            for a in assigned_by_lecturer.get(lec_id, []):
                for s in a.class_section.sessions:
                    day_counts[s.weekday] += 1
            for day, cnt in day_counts.items():
                if cnt > max_s:
                    errors.append({
                        "code": "MAX_SESSIONS_PER_DAY_EXCEEDED",
                        "lecturer_id": lec_id,
                        "weekday": day,
                        "actual": cnt,
                        "limit": max_s,
                        "message": f"GV {lec_id} dạy {cnt} ca vào thứ {day}, vượt giới hạn {max_s}",
                    })

        elif kind == "MAX_DAYS_PER_WEEK" and c.hardness == "hard" and lec_id:
            max_d = target.get("max", float("inf"))
            distinct_days = {s.weekday for a in assigned_by_lecturer.get(lec_id, []) for s in a.class_section.sessions}
            if len(distinct_days) > max_d:
                errors.append({
                    "code": "MAX_DAYS_PER_WEEK_EXCEEDED",
                    "lecturer_id": lec_id,
                    "actual": len(distinct_days),
                    "limit": max_d,
                    "message": f"GV {lec_id} dạy {len(distinct_days)} ngày trong tuần, vượt giới hạn {max_d}",
                })

        elif kind == "REQUIRED_ASSIGNMENT" and c.hardness == "hard" and lec_id:
            tgt_class_id = target.get("class_id")
            if tgt_class_id:
                assigned_to_lec = any(a.class_id == tgt_class_id for a in assigned_by_lecturer.get(lec_id, []))
                if not assigned_to_lec:
                    errors.append({
                        "code": "REQUIRED_ASSIGNMENT_VIOLATION",
                        "class_id": tgt_class_id,
                        "lecturer_id": lec_id,
                        "message": f"Lớp {tgt_class_id} bắt buộc phân công cho GV {lec_id}",
                    })

    # 5. Assignment coverage
    assigned_class_ids = {a.class_id for a in assignments}
    unassigned_count = len(all_semester_classes) - len(assigned_class_ids)
    if unassigned_count > 0:
        warnings.append({
            "code": "ASSIGNMENT_COVERAGE_INCOMPLETE",
            "unassigned_classes": unassigned_count,
            "total_classes": len(all_semester_classes),
            "message": f"Còn {unassigned_count}/{len(all_semester_classes)} lớp chưa được phân công",
        })

    return {
        "valid": not errors,
        "blocking_errors": errors,
        "warnings": warnings,
        "counts": {
            "assignments": len(assignments),
            "total_classes": len(all_semester_classes),
            "unassigned": unassigned_count,
            "hard_violations": len(errors),
        },
    }
