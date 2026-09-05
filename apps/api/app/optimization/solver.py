from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection, Constraint, Lecturer, LecturerCourseCapability, OptimizationRun, ValidationIssue


def _overlap(left, right) -> bool:
    if left.weekday != right.weekday or left.end_period < right.start_period or right.end_period < left.start_period:
        return False
    if not set(left.active_weeks).intersection(right.active_weeks):
        return False
    return not ((left.start_date and right.end_date and left.start_date > right.end_date) or (right.start_date and left.end_date and right.start_date > left.end_date))


def eligible_teachers(group: ClassSection, capabilities: dict[int, list[LecturerCourseCapability]]) -> set[int]:
    """The sole capability-based candidate gate for the solver."""
    return {item.lecturer_id for item in capabilities.get(group.course_id, []) if item.allowed and item.confirmed}


def _slot_match(session, target: dict) -> bool:
    slots = target.get("slots") or [target]
    for slot in slots:
        weekday = slot.get("weekday")
        periods = slot.get("periods") or slot.get("period_range") or []
        if weekday is not None and session.weekday != weekday:
            continue
        if periods and not any(session.start_period <= period <= session.end_period for period in periods):
            continue
        return True
    return False


def _normalized_type(value: str) -> str:
    return {"available": "PREFERRED", "prefer_period": "PREFERRED", "unavailable": "UNAVAILABLE", "seminar": "BUSY_EVENT"}.get(value.casefold(), value.upper())


def solve(db: Session, time_limit_seconds: int, confirm_merged: bool, semester_id: int) -> OptimizationRun:
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id == semester_id)).all()
    lecturers = db.scalars(select(Lecturer).order_by(Lecturer.id)).all()
    constraints = db.scalars(select(Constraint).where(Constraint.active.is_(True), Constraint.confirmed.is_(True), Constraint.semester_id == semester_id)).all()
    capabilities = defaultdict(list)
    for capability in db.scalars(select(LecturerCourseCapability)).all():
        capabilities[capability.course_id].append(capability)

    unsupported = [c.constraint_type for c in constraints if _normalized_type(c.constraint_type) not in {"UNAVAILABLE", "PREFERRED", "BUSY_EVENT", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "LOCKED_ASSIGNMENT"}]
    locked_conflicts = []
    for index, left in enumerate(classes):
        for right in classes[index + 1:]:
            if left.merged_confirmed and right.merged_confirmed and left.merged_group_id and left.merged_group_id == right.merged_group_id:
                continue
            if left.locked_assignment and right.locked_assignment and left.assigned_lecturer_id == right.assigned_lecturer_id and any(_overlap(a, b) for a in left.sessions for b in right.sessions):
                locked_conflicts.append((left.id, right.id))
    if locked_conflicts:
        run = OptimizationRun(semester_id=semester_id, status="blocked", summary={"code": "LOCKED_ASSIGNMENT_CONFLICT", "pairs": locked_conflicts, "unsupported_constraints": unsupported})
        db.add(run); db.commit(); return run

    model = cp_model.CpModel()
    base_candidates = {group.id: eligible_teachers(group, capabilities) for group in classes}
    candidates = {group.id: set(base_candidates[group.id]) for group in classes}
    reasons = {group.id: [] for group in classes}
    soft_penalties = []
    for constraint in constraints:
        kind = _normalized_type(constraint.constraint_type)
        if kind not in {"UNAVAILABLE", "PREFERRED", "BUSY_EVENT"} or not constraint.lecturer_id:
            continue
        for group in classes:
            if constraint.lecturer_id not in candidates[group.id]:
                continue
            matches = [_slot_match(session, constraint.target) for session in group.sessions]
            if kind in {"UNAVAILABLE", "BUSY_EVENT"} and any(matches):
                candidates[group.id].discard(constraint.lecturer_id)
                reasons[group.id].append({"lecturer_id": constraint.lecturer_id, "reason": "UNAVAILABLE"})
            elif kind == "PREFERRED" and not all(matches):
                soft_penalties.append((group.id, constraint.lecturer_id, max(1, int(constraint.weight * 100))))

    x = {(group.id, lecturer_id): model.new_bool_var(f"x_{group.id}_{lecturer_id}") for group in classes for lecturer_id in candidates[group.id]}
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
                run = OptimizationRun(semester_id=semester_id, status="blocked", summary={"code": "LOCKED_ASSIGNMENT_INVALID", "class_id": group.id, "unsupported_constraints": unsupported})
                db.add(run); db.commit(); return run
            model.add(x[group.id, group.assigned_lecturer_id] == 1)

    invalid_constraints = []
    for constraint in constraints:
        kind = _normalized_type(constraint.constraint_type)
        target = constraint.target or {}
        lecturer_id = constraint.lecturer_id
        limit = target.get("max")
        if kind == "MAX_CLASSES":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            model.add(sum(x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x) <= limit)
        elif kind == "MAX_SESSIONS_PER_DAY":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            for weekday in range(2, 9):
                model.add(sum(sum(s.weekday == weekday for s in g.sessions) * x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x) <= limit)
        elif kind == "MAX_DAYS_PER_WEEK":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            active_days = []
            for weekday in range(2, 9):
                day = model.new_bool_var(f"day_{lecturer_id}_{weekday}"); active_days.append(day)
                for g in classes:
                    if any(s.weekday == weekday for s in g.sessions) and (g.id, lecturer_id) in x: model.add(day >= x[g.id, lecturer_id])
            model.add(sum(active_days) <= limit)
        elif kind in {"REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT"}:
            class_id = target.get("class_id")
            if not lecturer_id or not isinstance(class_id, int) or (class_id, lecturer_id) not in x: invalid_constraints.append(constraint.id); continue
            model.add(x[class_id, lecturer_id] == (1 if kind == "REQUIRED_ASSIGNMENT" else 0))

    for index, left in enumerate(classes):
        for right in classes[index + 1:]:
            if left.merged_confirmed and right.merged_confirmed and left.merged_group_id and left.merged_group_id == right.merged_group_id:
                continue
            if any(_overlap(a, b) for a in left.sessions for b in right.sessions):
                for lecturer_id in candidates[left.id].intersection(candidates[right.id]):
                    model.add(x[left.id, lecturer_id] + x[right.id, lecturer_id] <= 1)
    groups = defaultdict(list)
    for group in classes:
        if group.merged_confirmed and group.merged_group_id:
            groups[group.merged_group_id].append(group)
    for items in groups.values():
        for other in items[1:]:
            for lecturer_id in candidates[items[0].id].intersection(candidates[other.id]):
                model.add(x[items[0].id, lecturer_id] == x[other.id, lecturer_id])

    loads = []
    for lecturer in lecturers:
        load = sum(int(group.credits * 10) * x[group.id, lecturer.id] for group in classes if (group.id, lecturer.id) in x)
        loads.append(load)
    max_load = model.new_int_var(0, 10000, "max_load"); min_load = model.new_int_var(0, 10000, "min_load")
    if loads:
        model.add_max_equality(max_load, loads); model.add_min_equality(min_load, loads)
    soft = sum(weight * x[group_id, lecturer_id] for group_id, lecturer_id, weight in soft_penalties if (group_id, lecturer_id) in x)
    # Lexicographic-safe scaling: a one-group completeness improvement always
    # outweighs every possible workload and soft-preference difference.
    model.minimize(sum(unassigned.values()) * 1_000_000 + (max_load - min_load) * 1_000 + soft)
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = time_limit_seconds; solver.parameters.num_search_workers = 8
    status = solver.solve(model); valid = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    summary = {"classes": len(classes), "unsupported_constraints": unsupported, "invalid_constraints": invalid_constraints, "unassigned": [], "candidate_reasons": reasons}
    run = OptimizationRun(semester_id=semester_id, status=solver.status_name(status).lower(), score=solver.objective_value if valid else None, summary=summary)
    db.add(run); db.flush()
    if valid:
        for group in classes:
            if solver.value(unassigned[group.id]):
                if not summary["candidate_reasons"][group.id]: summary["candidate_reasons"][group.id].append({"reason": "TIMETABLE_CONFLICT"})
                summary["unassigned"].append({"class_id": group.id, "reasons": summary["candidate_reasons"][group.id]})
                continue
            lecturer_id = next(lecturer_id for lecturer_id in candidates[group.id] if solver.value(x[group.id, lecturer_id]))
            db.add(Assignment(semester_id=semester_id, run_id=run.id, class_id=group.id, lecturer_id=lecturer_id, locked=group.locked_assignment, source="SOLVER"))
    db.commit(); return run
