from __future__ import annotations

from collections import defaultdict
from app.optimization.occurrences import meeting_occurrences

from ortools.sat.python import cp_model
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Assignment, ClassSection, Constraint, Course, Lecturer, LecturerCourseCapability,
    LecturerSemesterProfile, OptimizationRun, Semester, Seminar, ValidationIssue,
)


def _overlap(left, right) -> bool:
    if left.weekday != right.weekday or left.end_period < right.start_period or right.end_period < left.start_period:
        return False
    w_left = set(left.active_weeks or [])
    w_right = set(right.active_weeks or [])
    if w_left and w_right and not w_left.intersection(w_right):
        return False
    return not ((left.start_date and right.end_date and left.start_date > right.end_date) or (right.start_date and left.end_date and right.start_date > left.end_date))


def eligible_teachers(
    group: ClassSection,
    capabilities: dict[int, list[LecturerCourseCapability]],
    policy: Any = None,
) -> set[int]:
    """The sole capability-based candidate gate for the solver."""
    allow_provisional = getattr(policy, "allow_provisional_capability", False) if policy else False
    result = set()
    for item in capabilities.get(group.course_id, []):
        if not item.allowed or item.source == "HYPOTHETICAL_ALL":
            continue
        if item.confirmed or allow_provisional:
            result.add(item.lecturer_id)
    return result


def _slot_match(session, target: dict, semester: Semester | None = None) -> bool:
    from datetime import date
    slots = target.get("slots") or [target]
    for slot in slots:
        combined = {**target, **slot}
        scope = combined.get("day_scope")
        if scope:
            allowed_days = (
                {2, 3, 4, 5, 6} if scope == "ALL_WEEKDAYS"
                else {2, 3, 4, 5, 6, 7, 8} if scope == "ALL_DAYS"
                else {8} if scope in {"CN", "T8"}
                else {int(scope[1:])} if scope in {"T2", "T3", "T4", "T5", "T6", "T7", "T8"}
                else None
            )
            if allowed_days and session.weekday not in allowed_days:
                continue
        weekday = combined.get("weekday")
        if weekday is not None and session.weekday != weekday:
            continue
        periods = combined.get("periods") or combined.get("period_range") or []
        if periods and not any(session.start_period <= period <= session.end_period for period in periods):
            continue
        if not session.active_weeks:
            continue
        target_weeks = combined.get("weeks") or []
        if target_weeks and not set(target_weeks).intersection(session.active_weeks or []):
            continue
        target_start = combined.get("start_date")
        target_end = combined.get("end_date")
        if target_start or target_end:
            ts = (target_start if isinstance(target_start, date) else date.fromisoformat(str(target_start))) if target_start else None
            te = (target_end if isinstance(target_end, date) else date.fromisoformat(str(target_end))) if target_end else None
            s_start = session.start_date if isinstance(session.start_date, date) else (date.fromisoformat(str(session.start_date)) if session.start_date else None)
            s_end = session.end_date if isinstance(session.end_date, date) else (date.fromisoformat(str(session.end_date)) if session.end_date else None)

            if ts and s_end and s_end < ts:
                continue
            if te and s_start and s_start > te:
                continue

            if semester and getattr(semester, "start_date", None) and session.active_weeks:
                from datetime import timedelta
                anchor = semester.start_date
                monday = anchor - timedelta(days=anchor.weekday())
                has_valid_week = False
                for w in session.active_weeks:
                    actual = monday + timedelta(weeks=w - 1, days=session.weekday - 2)
                    if s_start and actual < s_start:
                        continue
                    if s_end and actual > s_end:
                        continue
                    if ts and actual < ts:
                        continue
                    if te and actual > te:
                        continue
                    has_valid_week = True
                    break
                if not has_valid_week:
                    continue
        return True
    return False


def _normalized_type(value: str) -> str:
    return {
        "available": "PREFERRED", "prefer_period": "PREFERRED", "avoid": "AVOID_PERIOD",
        "unavailable": "UNAVAILABLE", "busy_event": "BUSY_EVENT", "seminar": "BUSY_EVENT",
        "min_free_morning_per_week": "MIN_FREE_MORNING_PER_WEEK",
        "prefer_consecutive_periods": "PREFER_CONSECUTIVE_PERIODS",
        "compact_schedule": "PREFER_CONSECUTIVE_PERIODS",
        "prefer_compact_schedule": "PREFER_COMPACT_SCHEDULE",
        "preferred_days": "PREFERRED_DAYS", "avoid_days": "AVOID_DAYS",
        "prefer_low_workload": "PREFER_LOW_WORKLOAD",
    }.get(value.casefold(), value.upper())


def _weight(constraint: Constraint) -> int:
    """Weight is meaningful only for SOFT rules; 1.0 never changes hardness."""
    return max(0, round(float(constraint.weight) * 100))


def _event_slots(seminar: Seminar) -> list[dict]:
    alternatives = seminar.alternatives or []
    if isinstance(alternatives, dict):
        alternatives = alternatives.get("slots", [])
    return [slot for slot in alternatives if isinstance(slot, dict) and slot.get("weekday") is not None]


def solve(db: Session, time_limit_seconds: int = 30, confirm_merged: bool = False, semester_id: int | None = None) -> OptimizationRun:
    from app.services.lecturer_master import participation_reason
    semester = db.get(Semester, semester_id) if semester_id else db.scalar(select(Semester).where(Semester.is_active.is_(True)).order_by(Semester.id.desc()))
    if semester and semester_id is None:
        semester_id = semester.id
    if not semester:
        raise ValueError("Không tìm thấy kỳ học để chạy tối ưu.")
    from app.services.source_authority import source_blockers, SourceError, run_context
    blockers = source_blockers(db, semester_id)
    if blockers:
        raise SourceError("SOURCE_NOT_READY", "Nguồn có vấn đề cần xác nhận trước khi tối ưu.", blockers=blockers)
    context = run_context(semester)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id == semester_id)).all()
    lecturers = db.scalars(select(Lecturer).order_by(Lecturer.id)).all()
    constraints = db.scalars(select(Constraint).where(Constraint.active.is_(True), Constraint.confirmed.is_(True), Constraint.semester_id == semester_id)).all()
    seminars = db.scalars(select(Seminar).where(Seminar.semester_id == semester_id)).all()
    # Priority 1: Remove or disable all LecturerCourseCapability records sourced from HYPOTHETICAL_ALL
    hypo_caps = db.scalars(
        select(LecturerCourseCapability).where(LecturerCourseCapability.source == "HYPOTHETICAL_ALL")
    ).all()
    for cap in hypo_caps:
        cap.confirmed = False
        cap.allowed = False
    if hypo_caps:
        db.flush()

    policy = None
    if semester and semester.department_id:
        from app.models.entities import DepartmentProfile
        policy = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == semester.department_id))

    cap_query = select(LecturerCourseCapability).where(
        LecturerCourseCapability.allowed.is_(True),
        or_(
            LecturerCourseCapability.source.is_(None),
            LecturerCourseCapability.source != "HYPOTHETICAL_ALL",
        ),
    )
    if not (policy and policy.allow_provisional_capability):
        cap_query = cap_query.where(LecturerCourseCapability.confirmed.is_(True))
    if semester and semester.department_id:
        cap_query = cap_query.where(
            or_(
                LecturerCourseCapability.department_id == semester.department_id,
                LecturerCourseCapability.department_id.is_(None),
            )
        )

    capabilities = defaultdict(list)
    cap_source_map = {}
    cap_obj_map = {}
    confirmed_cap_count = 0
    historical_cap_count = 0
    provisional_cap_count = 0

    for capability in db.scalars(cap_query).all():
        capabilities[capability.course_id].append(capability)
        cap_source_map[(capability.course_id, capability.lecturer_id)] = capability.source
        cap_obj_map[(capability.course_id, capability.lecturer_id)] = capability
        if capability.confirmed:
            if capability.source in {"HISTORICAL_ASSIGNMENT", "HISTORICAL_TEMPLATE", "INFERRED_HISTORY"}:
                historical_cap_count += 1
            else:
                confirmed_cap_count += 1
        else:
            provisional_cap_count += 1

    forbidden_caps = {
        (c.course_id, c.lecturer_id)
        for c in db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.allowed.is_(False))).all()
    }

    # Capability equivalence bridging:
    # Connect courses with identical normalized names (e.g. regular 440213 vs retake 448805)
    # scoped strictly to the current semester's courses and department.
    from app.services.capability_resolution import _plain_text
    all_db_courses = db.scalars(select(Course)).all()
    courses_by_norm: dict[str, list[Course]] = defaultdict(list)
    for c in all_db_courses:
        if c.name:
            c_norm = _plain_text(c.name)
            if c_norm and len(c_norm) >= 3:
                courses_by_norm[c_norm].append(c)

    semester_course_ids = {g.course_id for g in classes if g.course_id}
    for norm_name, eq_courses in courses_by_norm.items():
        if len(eq_courses) < 2:
            continue
        eq_ids = {c.id for c in eq_courses}
        if not eq_ids.intersection(semester_course_ids):
            continue
        for src_course in eq_courses:
            for cap in list(capabilities.get(src_course.id, [])):
                if not cap.allowed or cap.source == "HYPOTHETICAL_ALL":
                    continue
                for dst_course in eq_courses:
                    if dst_course.id == src_course.id:
                        continue
                    if (dst_course.id, cap.lecturer_id) in forbidden_caps:
                        continue
                    if (dst_course.id, cap.lecturer_id) not in cap_obj_map:
                        bridged_cap = LecturerCourseCapability(
                            department_id=cap.department_id,
                            lecturer_id=cap.lecturer_id,
                            course_id=dst_course.id,
                            allowed=True,
                            confirmed=cap.confirmed,
                            source="INFERRED_HISTORY",
                        )
                        capabilities[dst_course.id].append(bridged_cap)
                        cap_source_map[(dst_course.id, cap.lecturer_id)] = "INFERRED_HISTORY"
                        cap_obj_map[(dst_course.id, cap.lecturer_id)] = bridged_cap
                        if bridged_cap.confirmed:
                            historical_cap_count += 1
                        else:
                            provisional_cap_count += 1

    def _is_merged(left: ClassSection, right: ClassSection) -> bool:
        if not (left.merged_group_id and left.merged_group_id == right.merged_group_id):
            return False
        if getattr(left, "merge_status", "") == "rejected" or getattr(right, "merge_status", "") == "rejected":
            return False
        return bool(
            (left.merged_confirmed and right.merged_confirmed)
            or getattr(left, "merge_status", "") == "confirmed"
            or getattr(right, "merge_status", "") == "confirmed"
            or confirm_merged
        )

    unsupported = [
        c.constraint_type for c in constraints
        if _normalized_type(c.constraint_type) not in {
            "UNAVAILABLE", "PREFERRED", "BUSY_EVENT", "MIN_CLASSES", "MAX_CLASSES",
            "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "MAX_CONSECUTIVE_BLOCKS",
            "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "LOCKED_ASSIGNMENT",
            "MIN_FREE_MORNING_PER_WEEK", "PREFER_CONSECUTIVE_PERIODS", "PREFER_COMPACT_SCHEDULE", "PREFERRED_DAYS", "AVOID_DAYS", "PREFER_LOW_WORKLOAD", "AVOID_PERIOD",
        }
    ]
    locked_conflicts = []
    for index, left in enumerate(classes):
        for right in classes[index + 1:]:
            if _is_merged(left, right):
                continue
            if left.locked_assignment and right.locked_assignment and left.assigned_lecturer_id == right.assigned_lecturer_id and any(_overlap(a, b) for a in left.sessions for b in right.sessions):
                locked_conflicts.append((left.id, right.id))
    if locked_conflicts:
        run = OptimizationRun(semester_id=semester_id, **context, status="blocked", summary={"code": "LOCKED_ASSIGNMENT_CONFLICT", "pairs": locked_conflicts, "unsupported_constraints": unsupported})
        db.add(run); db.commit(); return run

    model = cp_model.CpModel()
    participating_ids = {
        lecturer.id for lecturer in lecturers
        if (
            semester.department_id is None
            or lecturer.department_id is None
            or lecturer.department_id == semester.department_id
        )
        and participation_reason(db, lecturer, semester_id) is None
    }
    base_candidates = {
        group.id: (eligible_teachers(group, capabilities, policy) & participating_ids)
        - {lid for (cid, lid) in forbidden_caps if cid == group.course_id}
        for group in classes
    }

    groups_with_zero = sum(1 for gid, cands in base_candidates.items() if len(cands) == 0)
    groups_with_one = sum(1 for gid, cands in base_candidates.items() if len(cands) == 1)
    groups_with_multiple = sum(1 for gid, cands in base_candidates.items() if len(cands) > 1)

    dept_name = (semester.department.name if (semester and semester.department) else (semester.department_name if semester else None))
    dept_id = semester.department_id if semester else None
    course_cnt = len({g.course_id for g in classes})

    if len(classes) > 0 and groups_with_zero == len(classes):
        unassigned_items = []
        for g in classes:
            c_caps = capabilities.get(g.course_id, [])
            c_code = g.course.code if g.course else str(g.course_id)
            c_name = g.course.name if g.course else c_code
            diag_reason = {
                "reason": "NO_ELIGIBLE_LECTURER",
                "course": c_code,
                "course_code": c_code,
                "course_name": c_name,
                "capability_coverage": len(c_caps),
                "capability_records": len(c_caps),
                "affected_groups": sum(1 for other in classes if other.course_id == g.course_id),
                "recommended_remediation": "Import historical assignments, import a capability matrix, or manually approve capability.",
            }
            unassigned_items.append({
                "class_id": g.id,
                "course": c_code,
                "course_code": c_code,
                "course_name": c_name,
                "capability_coverage": len(c_caps),
                "capability_records": len(c_caps),
                "affected_groups": sum(1 for other in classes if other.course_id == g.course_id),
                "recommended_remediation": "Import historical assignments, import a capability matrix, or manually approve capability.",
                "reasons": [diag_reason],
            })
        summary = {
            "code": "DATA_READINESS_FAILURE",
            "message": f"Tất cả {len(classes)} TeachingGroups đều không có giảng viên đủ năng lực (0 ứng viên). Cần nạp file phân công lịch sử hoặc ma trận năng lực.",
            "classes": len(classes),
            "department": dept_name,
            "department_id": dept_id,
            "lecturer_count": len(participating_ids),
            "course_count": course_cnt,
            "teaching_group_count": len(classes),
            "groups_with_zero_candidates": groups_with_zero,
            "groups_with_one_candidate": groups_with_one,
            "groups_with_multiple_candidates": groups_with_multiple,
            "confirmed_capability_count": confirmed_cap_count,
            "historical_capability_count": historical_cap_count,
            "provisional_capability_count": provisional_cap_count,
            "unassigned": unassigned_items,
            "unsupported_constraints": unsupported,
        }
        run = OptimizationRun(semester_id=semester_id, **context, status="blocked", summary=summary)
        db.add(run)
        db.commit()
        return run

    candidates = {group.id: set(base_candidates[group.id]) for group in classes}
    reasons = {group.id: [] for group in classes}
    for group in classes:
        if len(base_candidates[group.id]) == 0:
            c_caps = capabilities.get(group.course_id, [])
            c_code = group.course.code if group.course else str(group.course_id)
            c_name = group.course.name if group.course else c_code
            reasons[group.id].append({
                "reason": "NO_ELIGIBLE_LECTURER",
                "course": c_code,
                "course_code": c_code,
                "course_name": c_name,
                "capability_coverage": len(c_caps),
                "capability_records": len(c_caps),
                "affected_groups": sum(1 for other in classes if other.course_id == group.course_id),
                "recommended_remediation": "Import historical assignments, import a capability matrix, or manually approve capability.",
            })
    soft_terms = []
    for constraint in constraints:
        kind = _normalized_type(constraint.constraint_type)
        if kind not in {"UNAVAILABLE", "PREFERRED", "BUSY_EVENT", "AVOID_PERIOD", "PREFERRED_DAYS", "AVOID_DAYS"} or not constraint.lecturer_id:
            continue
        for group in classes:
            if constraint.lecturer_id not in candidates[group.id]:
                continue
            matches = [_slot_match(session, constraint.target, semester) for session in group.sessions]
            if kind in {"PREFERRED_DAYS", "AVOID_DAYS"}:
                days = set((constraint.target or {}).get("weekdays") or [])
                matches = [session.weekday in days for session in group.sessions]
            if kind in {"UNAVAILABLE", "BUSY_EVENT", "AVOID_PERIOD", "AVOID_DAYS"} and any(matches):
                if constraint.hardness == "hard":
                    candidates[group.id].discard(constraint.lecturer_id)
                    reasons[group.id].append({"lecturer_id": constraint.lecturer_id, "reason": "HARD_AVAILABILITY_CONFLICT"})
                elif _weight(constraint):
                    penalty = int(_weight(constraint) * 0.6) if kind in {"AVOID_PERIOD", "AVOID_DAYS"} else _weight(constraint)
                    if penalty > 0:
                        soft_terms.append((penalty, (group.id, constraint.lecturer_id)))
            elif kind in {"PREFERRED", "PREFERRED_DAYS"} and not all(matches):
                if constraint.hardness == "hard":
                    candidates[group.id].discard(constraint.lecturer_id)
                    reasons[group.id].append({"lecturer_id": constraint.lecturer_id, "reason": "HARD_PREFERENCE_CONFLICT"})
                elif _weight(constraint):
                    soft_terms.append((_weight(constraint), (group.id, constraint.lecturer_id)))

    x = {(group.id, lecturer_id): model.new_bool_var(f"x_{group.id}_{lecturer_id}") for group in classes for lecturer_id in candidates[group.id]}
    for group in classes:
        for lecturer_id in candidates[group.id]:
            cap = cap_obj_map.get((group.course_id, lecturer_id))
            if cap:
                if not cap.confirmed:
                    soft_terms.append((50, x[group.id, lecturer_id]))
                elif cap.source in {"HISTORICAL_ASSIGNMENT", "HISTORICAL_TEMPLATE", "INFERRED_HISTORY"}:
                    soft_terms.append((5, x[group.id, lecturer_id]))
    unassigned = {group.id: model.new_bool_var(f"unassigned_{group.id}") for group in classes}
    for group in classes:
        vars_for_group = [x[group.id, lecturer_id] for lecturer_id in candidates[group.id]]
        model.add(sum(vars_for_group) + unassigned[group.id] == 1)
        if not base_candidates[group.id]:
            reasons[group.id].append({"reason": "NO_ELIGIBLE_LECTURER"})
        # A manual choice is editable again once its lock is removed.  Keeping
        # every MANUAL assignment fixed here made the unlock operation only
        # cosmetic: subsequent solver runs could never reconsider it.
        if group.assigned_lecturer_id and group.locked_assignment:
            if group.assigned_lecturer_id not in candidates[group.id]:
                run = OptimizationRun(semester_id=semester_id, **context, status="blocked", summary={"code": "LOCKED_ASSIGNMENT_INVALID", "class_id": group.id, "unsupported_constraints": unsupported})
                db.add(run); db.commit(); return run
            model.add(x[group.id, group.assigned_lecturer_id] == 1)

    groups = defaultdict(list)
    for group in classes:
        if (
            group.merged_group_id
            and getattr(group, "merge_status", "") != "rejected"
            and (group.merged_confirmed or getattr(group, "merge_status", "") == "confirmed" or confirm_merged)
        ):
            groups[group.merged_group_id].append(group)
    active_groups = {gid: items for gid, items in groups.items() if len(items) >= 2}
    for items in active_groups.values():
        common_candidates = set(candidates[items[0].id])
        for other in items[1:]:
            common_candidates &= candidates[other.id]
        for sec in items:
            for lecturer_id in candidates[sec.id] - common_candidates:
                if (sec.id, lecturer_id) in x:
                    model.add(x[sec.id, lecturer_id] == 0)
        for other in items[1:]:
            for lecturer_id in common_candidates:
                if (items[0].id, lecturer_id) in x and (other.id, lecturer_id) in x:
                    model.add(x[items[0].id, lecturer_id] == x[other.id, lecturer_id])

    # Workload and class counts for merged groups must be counted once per group
    secondary_merged_ids = {
        sec.id
        for items in active_groups.values()
        for sec in items[1:]
    }
    representative_classes = [g for g in classes if g.id not in secondary_merged_ids]

    invalid_constraints = []
    def bounded_violation(expression, limit: int, upper_bound: int, constraint: Constraint, *, minimum: bool = False):
        """Enforce HARD bounds and score SOFT bounds without conflating weight/hardness."""
        if constraint.hardness == "hard":
            model.add(expression >= limit if minimum else expression <= limit)
            return
        if not _weight(constraint):
            return
        violation = model.new_int_var(0, max(0, upper_bound), f"violation_{constraint.id}_{'min' if minimum else 'max'}")
        if minimum:
            model.add(violation >= limit - expression)
        else:
            model.add(violation >= expression - limit)
        soft_terms.append((_weight(constraint), violation))

    for constraint in constraints:
        kind = _normalized_type(constraint.constraint_type)
        target = constraint.target or {}
        lecturer_id = constraint.lecturer_id
        limit = target.get("max")
        if kind == "MAX_CLASSES":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            expression = sum(x[g.id, lecturer_id] for g in representative_classes if (g.id, lecturer_id) in x)
            bounded_violation(expression, limit, len(representative_classes), constraint)
        elif kind == "MIN_CLASSES":
            limit = target.get("min")
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            expression = sum(x[g.id, lecturer_id] for g in representative_classes if (g.id, lecturer_id) in x)
            bounded_violation(expression, limit, len(representative_classes), constraint, minimum=True)
        elif kind == "MAX_SESSIONS_PER_DAY":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            for weekday in range(2, 9):
                expression = sum(sum(s.weekday == weekday for s in g.sessions) * x[g.id, lecturer_id] for g in representative_classes if (g.id, lecturer_id) in x)
                bounded_violation(expression, limit, len(representative_classes), constraint)
        elif kind == "MAX_DAYS_PER_WEEK":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            active_days = []
            for weekday in range(2, 9):
                day = model.new_bool_var(f"day_{lecturer_id}_{weekday}"); active_days.append(day)
                for g in classes:
                    if any(s.weekday == weekday for s in g.sessions) and (g.id, lecturer_id) in x: model.add(day >= x[g.id, lecturer_id])
            bounded_violation(sum(active_days), limit, 7, constraint)
        elif kind == "MAX_CONSECUTIVE_BLOCKS":
            if not lecturer_id or not isinstance(limit, int) or limit < 1: invalid_constraints.append(constraint.id); continue
            for weekday in range(2, 9):
                active_blocks = []
                for block_index, (start, end) in enumerate(((1, 3), (4, 6), (7, 9), (10, 12), (13, 15))):
                    relevant = [x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x and any(s.weekday == weekday and not (s.end_period < start or end < s.start_period) for s in g.sessions)]
                    active = model.new_bool_var(f"block_{constraint.id}_{weekday}_{block_index}")
                    if relevant:
                        model.add(active <= sum(relevant))
                        for item in relevant: model.add(active >= item)
                    else:
                        model.add(active == 0)
                    active_blocks.append(active)
                for index in range(0, max(0, len(active_blocks) - limit)):
                    window = sum(active_blocks[index:index + limit + 1])
                    bounded_violation(window, limit, limit + 1, constraint)
        elif kind in {"REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT"}:
            class_id = target.get("class_id")
            course_id = target.get("course_id")
            class_ids = [class_id] if isinstance(class_id, int) else [group.id for group in classes if kind == "FORBIDDEN_ASSIGNMENT" and group.course_id == course_id]
            if not lecturer_id or not class_ids or any((item, lecturer_id) not in x for item in class_ids): invalid_constraints.append(constraint.id); continue
            wanted = 1 if kind == "REQUIRED_ASSIGNMENT" else 0
            for scoped_class_id in class_ids:
                if constraint.hardness == "hard":
                    model.add(x[scoped_class_id, lecturer_id] == wanted)
                elif _weight(constraint):
                    # Required pays when absent; forbidden pays when present.
                    soft_terms.append((_weight(constraint), (1 - x[scoped_class_id, lecturer_id]) if wanted else x[scoped_class_id, lecturer_id]))
        elif kind == "MIN_FREE_MORNING_PER_WEEK":
            if not lecturer_id:
                invalid_constraints.append(constraint.id)
                continue
            limit = int(target.get("value") or target.get("numeric_value") or 1)
            day_list = [2, 3, 4, 5, 6]
            occurrences = {s.id: {w for w, _ in meeting_occurrences(s, semester, target)} for g in classes for s in g.sessions}
            active_weeks_set = set().union(*occurrences.values()) if occurrences else set()
            for w in sorted(active_weeks_set):
                busy_mornings = []
                for d in day_list:
                    relevant = [
                        x[g.id, lecturer_id]
                        for g in classes
                        if (g.id, lecturer_id) in x and any(
                            s.weekday == d
                            and w in occurrences[s.id]
                            and not (s.end_period < 1 or s.start_period > 6)
                            for s in g.sessions
                        )
                    ]
                    if relevant:
                        is_busy = model.new_bool_var(f"busy_morn_{constraint.id}_{w}_{d}")
                        model.add(is_busy <= sum(relevant))
                        for item in relevant:
                            model.add(is_busy >= item)
                        busy_mornings.append(is_busy)
                max_busy = max(0, len(day_list) - limit)
                if busy_mornings:
                    bounded_violation(sum(busy_mornings), max_busy, len(busy_mornings), constraint)
        elif kind in {"PREFER_CONSECUTIVE_PERIODS", "PREFER_COMPACT_SCHEDULE"}:
            if not lecturer_id:
                invalid_constraints.append(constraint.id)
                continue
            weight = 80 if constraint.weight is None else _weight(constraint)
            if weight == 0:
                continue
            occurrences = {s.id: {w for w, _ in meeting_occurrences(s, semester, target)} for g in classes for s in g.sessions}
            active_weeks_set = set().union(*occurrences.values()) if occurrences else set()
            # Each empty period between the first and last occupied period is
            # counted once, irrespective of how many meeting pairs span it.
            for w in sorted(active_weeks_set):
                for d in range(2, 9):
                    block_vars = []
                    for b_idx in range(15):
                        relevant = [
                            x[g.id, lecturer_id]
                            for g in classes
                            if (g.id, lecturer_id) in x and any(
                                s.weekday == d
                                and w in occurrences[s.id]
                                and s.start_period <= b_idx + 1 <= s.end_period
                                for s in g.sessions
                            )
                        ]
                        b_occ = model.new_bool_var(f"pref_cons_occ_{constraint.id}_{w}_{d}_{b_idx}")
                        if relevant:
                            model.add(b_occ <= sum(relevant))
                            for item in relevant:
                                model.add(b_occ >= item)
                        else:
                            model.add(b_occ == 0)
                        block_vars.append(b_occ)

                    for mid in range(1, 14):
                        has_earlier = model.new_bool_var(f"pref_cons_earlier_{constraint.id}_{w}_{d}_{mid}")
                        model.add(has_earlier <= sum(block_vars[:mid]))
                        for item in block_vars[:mid]:
                            model.add(has_earlier >= item)

                        has_later = model.new_bool_var(f"pref_cons_later_{constraint.id}_{w}_{d}_{mid}")
                        model.add(has_later <= sum(block_vars[mid + 1:]))
                        for item in block_vars[mid + 1:]:
                            model.add(has_later >= item)

                        is_gap = model.new_bool_var(f"pref_cons_gap_{constraint.id}_{w}_{d}_{mid}")
                        model.add(is_gap >= has_earlier + has_later + (1 - block_vars[mid]) - 2)
                        model.add(is_gap <= has_earlier)
                        model.add(is_gap <= has_later)
                        model.add(is_gap <= 1 - block_vars[mid])

                        soft_terms.append((weight, is_gap))
            # Compact schedules also avoid spreading a lecturer over many days.
            if kind == "PREFER_COMPACT_SCHEDULE":
                for w in sorted(active_weeks_set):
                    active_days=[]
                    for d in range(2,9):
                        relevant=[x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x and any(s.weekday==d and w in occurrences[s.id] for s in g.sessions)]
                        day=model.new_bool_var(f"compact_day_{constraint.id}_{w}_{d}")
                        if relevant:
                            model.add(day <= sum(relevant))
                            for item in relevant: model.add(day >= item)
                        else: model.add(day == 0)
                        active_days.append(day)
                    extra=model.new_int_var(0, 6, f"compact_days_{constraint.id}_{w}")
                    model.add(extra >= sum(active_days)-1)
                    soft_terms.append((weight, extra))
        elif kind == "PREFER_LOW_WORKLOAD":
            if not lecturer_id:
                invalid_constraints.append(constraint.id); continue
            # Convex soft cost: assignments after the first become progressively
            # less attractive.  This is intentionally not a hidden MAX_CLASSES.
            scoped=[]
            for group in representative_classes:
                if (group.id, lecturer_id) not in x: continue
                if any(_slot_match(session, target, semester) for session in group.sessions) if (target.get('start_date') or target.get('end_date')) else True:
                    scoped.append(x[group.id, lecturer_id])
            if scoped and _weight(constraint):
                load=sum(scoped)
                for threshold in range(2, len(scoped)+1):
                    exceeded=model.new_bool_var(f"low_load_{constraint.id}_{threshold}")
                    model.add(load >= threshold).only_enforce_if(exceeded)
                    model.add(load < threshold).only_enforce_if(exceeded.Not())
                    soft_terms.append((_weight(constraint) * (threshold-1), exceeded))

    for index, left in enumerate(classes):
        for right in classes[index + 1:]:
            if _is_merged(left, right):
                continue
            if any(_overlap(a, b) for a in left.sessions for b in right.sessions):
                for lecturer_id in candidates[left.id].intersection(candidates[right.id]):
                    if (left.id, lecturer_id) in x and (right.id, lecturer_id) in x:
                        model.add(x[left.id, lecturer_id] + x[right.id, lecturer_id] <= 1)

    # A seminar is one shared event: one slot is selected for all participants,
    # rather than storing a duplicate personal seminar constraint per lecturer.
    seminar_choices = []
    for seminar in seminars:
        participants = [member for member in (seminar.members or []) if isinstance(member, int)]
        slots = _event_slots(seminar)
        if not participants or not slots:
            continue
        choice_vars = [model.new_bool_var(f"seminar_{seminar.id}_{index}") for index in range(len(slots))]
        if seminar.hardness == "hard":
            model.add(sum(choice_vars) == 1)
        else:
            skipped = model.new_bool_var(f"seminar_{seminar.id}_skipped")
            model.add(sum(choice_vars) + skipped == 1)
            if _weight(seminar):
                soft_terms.append((_weight(seminar), skipped))
        for slot, choice in zip(slots, choice_vars):
            for group in classes:
                if not any(_slot_match(session, slot, semester) for session in group.sessions):
                    continue
                for lecturer_id in participants:
                    if (group.id, lecturer_id) in x:
                        model.add(x[group.id, lecturer_id] + choice <= 1)
        seminar_choices.append((seminar, slots, choice_vars))

    participating_loads = []
    zero_assigned_penalties = []
    profiles = {p.lecturer_id: p for p in db.scalars(select(LecturerSemesterProfile).where(LecturerSemesterProfile.semester_id == semester_id))}
    for lecturer in lecturers:
        if lecturer.id not in participating_ids:
            continue
        lec_vars = [x[group.id, lecturer.id] for group in representative_classes if (group.id, lecturer.id) in x]
        if not lec_vars:
            continue
        load = sum(int(group.credits * 10) * v for v in lec_vars)
        participating_loads.append(load)

        # Strongly penalize leaving an active participating teacher with 0 classes
        is_zero = model.new_bool_var(f"zero_classes_{lecturer.id}")
        class_count = sum(lec_vars)
        model.add(class_count == 0).only_enforce_if(is_zero)
        model.add(class_count >= 1).only_enforce_if(is_zero.Not())
        zero_assigned_penalties.append(is_zero)

        prof = profiles.get(lecturer.id)
        if prof:
            if prof.min_workload and prof.min_workload > 0:
                min_credits_scaled = int(prof.min_workload * 10)
                shortfall = model.new_int_var(0, min_credits_scaled, f"shortfall_{lecturer.id}")
                model.add(shortfall >= min_credits_scaled - load)
                soft_terms.append((500, shortfall))
            if prof.max_workload and prof.max_workload > 0:
                max_credits_scaled = int(prof.max_workload * 10)
                excess = model.new_int_var(0, 10000, f"excess_{lecturer.id}")
                model.add(excess >= load - max_credits_scaled)
                soft_terms.append((500, excess))

    max_load = model.new_int_var(0, 10000, "max_load")
    min_load = model.new_int_var(0, 10000, "min_load")
    if participating_loads:
        model.add_max_equality(max_load, participating_loads)
        model.add_min_equality(min_load, participating_loads)
    else:
        model.add(max_load == 0)
        model.add(min_load == 0)

    soft = sum(
        weight * (x[value[0], value[1]] if isinstance(value, tuple) else value)
        for weight, value in soft_terms
        if not isinstance(value, tuple) or value in x
    )
    # Lexicographic-safe scaling:
    # 1. unassigned class penalty: 1,000,000 per class (Priority 1: completeness)
    # 2. active teacher zero-class penalty: 100,000 per teacher (Priority 2: participation fairness)
    # 3. workload disparity penalty: (max_load - min_load) * 1,000 (Priority 3: workload balance)
    # 4. soft preferences (Priority 4)
    model.minimize(
        sum(unassigned.values()) * 1_000_000
        + sum(zero_assigned_penalties) * 100_000
        + (max_load - min_load) * 1_000
        + soft
    )
    import logging
    logger = logging.getLogger("app.optimization.solver")
    logger.info(
        "Candidate coverage:\n"
        f"{len(classes)} total groups\n"
        f"{groups_with_zero} groups with zero candidates\n"
        f"{groups_with_one} groups with exactly 1 candidate\n"
        f"{groups_with_multiple} groups with 2+ candidates"
    )
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = time_limit_seconds; solver.parameters.num_search_workers = 8
    status = solver.solve(model); valid = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    summary = {
        "classes": len(classes),
        "department": dept_name,
        "department_id": dept_id,
        "lecturer_count": len(participating_ids),
        "course_count": course_cnt,
        "teaching_group_count": len(classes),
        "confirmed_capability_count": confirmed_cap_count,
        "historical_capability_count": historical_cap_count,
        "provisional_capability_count": provisional_cap_count,
        "groups_with_zero_candidates": groups_with_zero,
        "groups_with_one_candidate": groups_with_one,
        "groups_with_multiple_candidates": groups_with_multiple,
        "unsupported_constraints": unsupported,
        "invalid_constraints": invalid_constraints,
        "unassigned": [],
        "candidate_reasons": reasons,
        "seminars": [],
    }
    run = OptimizationRun(semester_id=semester_id, **context, status=solver.status_name(status).lower(), score=solver.objective_value if valid else None, summary=summary)
    db.add(run); db.flush()
    if valid:
        if confirm_merged:
            for items in groups.values():
                for sec in items:
                    sec.merged_confirmed = True
                    sec.merge_status = "confirmed"
        for seminar, slots, choices in seminar_choices:
            selected = next((slot for slot, choice in zip(slots, choices) if solver.value(choice)), None)
            summary["seminars"].append({"id": seminar.id, "name": seminar.name, "slot": selected, "scheduled": selected is not None})
        for group in classes:
            if solver.value(unassigned[group.id]):
                if not summary["candidate_reasons"][group.id]: summary["candidate_reasons"][group.id].append({"reason": "TIMETABLE_CONFLICT"})
                c_caps = capabilities.get(group.course_id, [])
                c_code = group.course.code if group.course else str(group.course_id)
                c_name = group.course.name if group.course else c_code
                affected_cnt = sum(1 for other in classes if other.course_id == group.course_id)
                remediation = "Import historical assignments, import a capability matrix, or manually approve capability."
                if len(c_caps) > 0 and len(candidates[group.id]) == 0:
                    remediation = "Toàn bộ giảng viên có năng lực bị bận cứng hoặc trùng lịch vào khung giờ này. Hãy nới lỏng nguyện vọng hoặc ghép lớp học phần."
                elif len(c_caps) > 0 and len(candidates[group.id]) > 0:
                    remediation = "Nghẽn tài nguyên khung giờ do nhiều lớp cùng ca. Hãy ghép lớp học phần cùng khung giờ hoặc nới lỏng nguyện vọng giảng viên."
                summary["unassigned"].append({
                    "class_id": group.id,
                    "course": c_code,
                    "course_code": c_code,
                    "course_name": c_name,
                    "capability_coverage": len(c_caps),
                    "capability_records": len(c_caps),
                    "affected_groups": affected_cnt,
                    "recommended_remediation": remediation,
                    "reasons": summary["candidate_reasons"][group.id],
                })
                continue
            lecturer_id = next(lecturer_id for lecturer_id in candidates[group.id] if solver.value(x[group.id, lecturer_id]))
            db.add(Assignment(semester_id=semester_id, run_id=run.id, class_id=group.id, lecturer_id=lecturer_id, locked=group.locked_assignment, source="SOLVER"))
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(run, "summary")
    db.commit(); return run
