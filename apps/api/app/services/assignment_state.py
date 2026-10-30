"""One current assignment authority, with immutable manual versions."""
from copy import deepcopy
from sqlalchemy import select
from app.models.entities import Assignment, ClassSection, OptimizationRun, Semester


def assignment_state(db, semester_id, run=None):
    from app.services.source_authority import latest_plan_run
    run = run or latest_plan_run(db, semester_id)
    groups = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    if run and run.semester_id == semester_id and run.status in {"optimal", "feasible"}:
        return {a.class_id: (a.lecturer_id, a.source, a.locked)
                for a in db.scalars(select(Assignment).where(Assignment.run_id == run.id))}
    return {g.id: (g.assigned_lecturer_id, g.assignment_source, g.locked_assignment)
            for g in groups if g.assigned_lecturer_id is not None}


def save_manual_version(db, semester_id, changes):
    """Persist a complete editable solution without rewriting solver history/metrics.

    `changes`: class_id -> (lecturer_id, source, locked). Caller commits atomically.
    Manual versions are feasible snapshots, not new optimality certificates.
    """
    from app.services.source_authority import latest_plan_run, run_context
    previous = latest_plan_run(db, semester_id)
    state = assignment_state(db, semester_id, previous)
    state.update(changes)
    summary = deepcopy(previous.summary) if previous else {}
    summary.pop("code", None)
    summary.update(solution_origin="MANUAL", parent_run_id=previous.id if previous else None,
                   experiment=None, manual_changes=sorted(changes))
    groups = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    prior_unassigned = {r["class_id"]: r for r in summary.get("unassigned", [])}
    summary["unassigned"] = [prior_unassigned.get(g.id, {"class_id": g.id, "reasons": []})
                             for g in groups if g.id not in state]
    run = OptimizationRun(semester_id=semester_id, **run_context(db.get(Semester, semester_id)),
                          status="feasible", score=None, summary=summary)
    db.add(run)
    db.flush()
    for cid, (lid, source, locked) in state.items():
        db.add(Assignment(semester_id=semester_id, run_id=run.id, class_id=cid,
                          lecturer_id=lid, source=source or "IMPORT", locked=locked))
    return run
