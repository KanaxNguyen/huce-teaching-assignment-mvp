from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Assignment, ClassSection, Constraint, Lecturer, LecturerCourseCapability, OptimizationRun, Seminar, ValidationIssue


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
    # A calendar rule can apply to the whole semester or only a bounded date
    # range. It conflicts when the meeting and rule ranges overlap.
    target_start = target.get("start_date")
    target_end = target.get("end_date")
    if target_start and session.end_date and str(target_start) > session.end_date.isoformat():
        return False
    if target_end and session.start_date and str(target_end) < session.start_date.isoformat():
        return False
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
    return {
        "available": "PREFERRED", "prefer_period": "PREFERRED", "avoid": "UNAVAILABLE",
        "unavailable": "UNAVAILABLE", "busy_event": "BUSY_EVENT", "seminar": "BUSY_EVENT",
    }.get(value.casefold(), value.upper())


def _weight(constraint: Constraint) -> int:
    """Weight is meaningful only for SOFT rules; 1.0 never changes hardness."""
    return max(0, round(float(constraint.weight) * 100))


def _event_slots(seminar: Seminar) -> list[dict]:
    alternatives = seminar.alternatives or []
    if isinstance(alternatives, dict):
        alternatives = alternatives.get("slots", [])
    return [slot for slot in alternatives if isinstance(slot, dict) and slot.get("weekday") is not None]


def solve(db: Session, time_limit_seconds: int, confirm_merged: bool, semester_id: int) -> OptimizationRun:
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id == semester_id)).all()
    lecturers = db.scalars(select(Lecturer).order_by(Lecturer.id)).all()
    constraints = db.scalars(select(Constraint).where(Constraint.active.is_(True), Constraint.confirmed.is_(True), Constraint.semester_id == semester_id)).all()
    seminars = db.scalars(select(Seminar).where(Seminar.semester_id == semester_id)).all()
    capabilities = defaultdict(list)
    for capability in db.scalars(select(LecturerCourseCapability)).all():
        capabilities[capability.course_id].append(capability)

    unsupported = [c.constraint_type for c in constraints if _normalized_type(c.constraint_type) not in {"UNAVAILABLE", "PREFERRED", "BUSY_EVENT", "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "MAX_CONSECUTIVE_BLOCKS", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "LOCKED_ASSIGNMENT"}]
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
    soft_terms = []
    for constraint in constraints:
        kind = _normalized_type(constraint.constraint_type)
        if kind not in {"UNAVAILABLE", "PREFERRED", "BUSY_EVENT"} or not constraint.lecturer_id:
            continue
        for group in classes:
            if constraint.lecturer_id not in candidates[group.id]:
                continue
            matches = [_slot_match(session, constraint.target) for session in group.sessions]
            if kind in {"UNAVAILABLE", "BUSY_EVENT"} and any(matches):
                if constraint.hardness == "hard":
                    candidates[group.id].discard(constraint.lecturer_id)
                    reasons[group.id].append({"lecturer_id": constraint.lecturer_id, "reason": "HARD_AVAILABILITY_CONFLICT"})
                elif _weight(constraint):
                    soft_terms.append((_weight(constraint), (group.id, constraint.lecturer_id)))
            elif kind == "PREFERRED" and not all(matches):
                if constraint.hardness == "hard":
                    candidates[group.id].discard(constraint.lecturer_id)
                    reasons[group.id].append({"lecturer_id": constraint.lecturer_id, "reason": "HARD_PREFERENCE_CONFLICT"})
                elif _weight(constraint):
                    soft_terms.append((_weight(constraint), (group.id, constraint.lecturer_id)))

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
            expression = sum(x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x)
            bounded_violation(expression, limit, len(classes), constraint)
        elif kind == "MIN_CLASSES":
            limit = target.get("min")
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            expression = sum(x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x)
            bounded_violation(expression, limit, len(classes), constraint, minimum=True)
        elif kind == "MAX_SESSIONS_PER_DAY":
            if not lecturer_id or not isinstance(limit, int): invalid_constraints.append(constraint.id); continue
            for weekday in range(2, 9):
                expression = sum(sum(s.weekday == weekday for s in g.sessions) * x[g.id, lecturer_id] for g in classes if (g.id, lecturer_id) in x)
                bounded_violation(expression, limit, len(classes), constraint)
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
                for block_index, (start, end) in enumerate(((1, 3), (4, 6), (7, 9), (10, 12))):
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
                if not any(_slot_match(session, slot) for session in group.sessions):
                    continue
                for lecturer_id in participants:
                    if (group.id, lecturer_id) in x:
                        model.add(x[group.id, lecturer_id] + choice <= 1)
        seminar_choices.append((seminar, slots, choice_vars))

    loads = []
    for lecturer in lecturers:
        load = sum(int(group.credits * 10) * x[group.id, lecturer.id] for group in classes if (group.id, lecturer.id) in x)
        loads.append(load)
    max_load = model.new_int_var(0, 10000, "max_load"); min_load = model.new_int_var(0, 10000, "min_load")
    if loads:
        model.add_max_equality(max_load, loads); model.add_min_equality(min_load, loads)
    soft = sum(
        weight * (x[value[0], value[1]] if isinstance(value, tuple) else value)
        for weight, value in soft_terms
        if not isinstance(value, tuple) or value in x
    )
    # Lexicographic-safe scaling: a one-group completeness improvement always
    # outweighs every possible workload and soft-preference difference.
    model.minimize(sum(unassigned.values()) * 1_000_000 + (max_load - min_load) * 1_000 + soft)
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = time_limit_seconds; solver.parameters.num_search_workers = 8
    status = solver.solve(model); valid = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    summary = {"classes": len(classes), "unsupported_constraints": unsupported, "invalid_constraints": invalid_constraints, "unassigned": [], "candidate_reasons": reasons, "seminars": []}
    run = OptimizationRun(semester_id=semester_id, status=solver.status_name(status).lower(), score=solver.objective_value if valid else None, summary=summary)
    db.add(run); db.flush()
    if valid:
        for seminar, slots, choices in seminar_choices:
            selected = next((slot for slot, choice in zip(slots, choices) if solver.value(choice)), None)
            summary["seminars"].append({"id": seminar.id, "name": seminar.name, "slot": selected, "scheduled": selected is not None})
        for group in classes:
            if solver.value(unassigned[group.id]):
                if not summary["candidate_reasons"][group.id]: summary["candidate_reasons"][group.id].append({"reason": "TIMETABLE_CONFLICT"})
                summary["unassigned"].append({"class_id": group.id, "reasons": summary["candidate_reasons"][group.id]})
                continue
            lecturer_id = next(lecturer_id for lecturer_id in candidates[group.id] if solver.value(x[group.id, lecturer_id]))
            db.add(Assignment(semester_id=semester_id, run_id=run.id, class_id=group.id, lecturer_id=lecturer_id, locked=group.locked_assignment, source="SOLVER"))
    db.commit(); return run
