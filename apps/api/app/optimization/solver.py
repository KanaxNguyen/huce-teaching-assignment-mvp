from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Assignment,
    ClassSection,
    Constraint,
    Lecturer,
    OptimizationRun,
    ValidationIssue,
)


def _overlap(left, right) -> bool:
    if left.weekday != right.weekday:
        return False
    if left.end_period < right.start_period or right.end_period < left.start_period:
        return False
    if not set(left.active_weeks).intersection(right.active_weeks):
        return False
    if left.start_date and right.end_date and left.start_date > right.end_date:
        return False
    if right.start_date and left.end_date and right.start_date > left.end_date:
        return False
    return True


def solve(db: Session, time_limit_seconds: int = 20, confirm_merged: bool = False) -> OptimizationRun:
    blocking = db.scalar(select(ValidationIssue).where(ValidationIssue.severity == "error").limit(1))
    if blocking:
        raise ValueError("Còn lỗi nghiêm trọng trong dữ liệu; cần xử lý trước khi tối ưu.")

    classes = db.scalars(
        select(ClassSection)
        .options(
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.course),
            selectinload(ClassSection.assigned_lecturer),
        )
        .order_by(ClassSection.id)
    ).all()
    lecturers = db.scalars(select(Lecturer).order_by(Lecturer.id)).all()
    constraints = db.scalars(select(Constraint).where(Constraint.active.is_(True))).all()
    if not classes or not lecturers:
        raise ValueError("Chưa có đủ lớp và giảng viên để tối ưu.")

    model = cp_model.CpModel()
    x = {
        (class_item.id, lecturer.id): model.new_bool_var(f"x_{class_item.id}_{lecturer.id}")
        for class_item in classes
        for lecturer in lecturers
    }
    for c in classes:
        model.add(sum(x[c.id, lecturer.id] for lecturer in lecturers) == 1)
        if c.locked_assignment and c.assigned_lecturer_id:
            model.add(x[c.id, c.assigned_lecturer_id] == 1)

    conflicts = []
    locked_overlap_exceptions = []
    for index, left in enumerate(classes):
        for right in classes[index + 1 :]:
            if left.merged_group_id and left.merged_group_id == right.merged_group_id:
                continue
            if any(_overlap(a, b) for a in left.sessions for b in right.sessions):
                if (
                    left.locked_assignment
                    and right.locked_assignment
                    and left.assigned_lecturer_id == right.assigned_lecturer_id
                ):
                    locked_overlap_exceptions.append((left.id, right.id))
                    continue
                conflicts.append((left.id, right.id))
                for lecturer in lecturers:
                    model.add(x[left.id, lecturer.id] + x[right.id, lecturer.id] <= 1)

    if confirm_merged:
        groups: dict[str, list[ClassSection]] = defaultdict(list)
        for item in classes:
            if item.merged_group_id:
                groups[item.merged_group_id].append(item)
        for items in groups.values():
            anchor = items[0]
            for other in items[1:]:
                for lecturer in lecturers:
                    model.add(x[anchor.id, lecturer.id] == x[other.id, lecturer.id])

    penalty_terms = []
    for constraint in constraints:
        if not constraint.lecturer_id or constraint.constraint_type not in {
            "unavailable",
            "prefer_period",
            "seminar",
        }:
            continue
        weekday = constraint.target.get("weekday")
        periods = constraint.target.get("periods") or constraint.target.get("period_range") or []
        for class_item in classes:
            violates = any(
                (weekday is None or session.weekday == weekday)
                and (
                    not periods
                    or any(session.start_period <= period <= session.end_period for period in periods)
                )
                for session in class_item.sessions
            )
            if not violates:
                continue
            variable = x[class_item.id, constraint.lecturer_id]
            if constraint.hardness == "hard":
                model.add(variable == 0)
            else:
                penalty_terms.append(int(round(constraint.weight * 100)) * variable)

    max_load = model.new_int_var(0, 1000, "max_load")
    min_load = model.new_int_var(0, 1000, "min_load")
    loads = []
    for lecturer in lecturers:
        load = model.new_int_var(0, 1000, f"load_{lecturer.id}")
        model.add(load == sum(int(round(c.credits * 10)) * x[c.id, lecturer.id] for c in classes))
        model.add(load <= int(round(lecturer.max_credits * 10)))
        loads.append(load)
    model.add_max_equality(max_load, loads)
    model.add_min_equality(min_load, loads)
    model.minimize(sum(penalty_terms) + (max_load - min_load))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.solve(model)
    status_name = solver.status_name(status)
    run = OptimizationRun(
        status=status_name.lower(),
        score=solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        summary={
            "classes": len(classes),
            "lecturers": len(lecturers),
            "hard_conflict_pairs": len(conflicts),
            "locked_overlap_exceptions": len(locked_overlap_exceptions),
            "merged_groups_confirmed": confirm_merged,
        },
    )
    db.add(run)
    db.flush()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for class_item in classes:
            lecturer = next(item for item in lecturers if solver.value(x[class_item.id, item.id]))
            db.add(
                Assignment(
                    run_id=run.id,
                    class_id=class_item.id,
                    lecturer_id=lecturer.id,
                    locked=class_item.locked_assignment,
                )
            )
            class_item.assigned_lecturer_id = lecturer.id
    db.commit()
    return run
