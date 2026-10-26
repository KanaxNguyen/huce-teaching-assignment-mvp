"""Algorithm audit: brute-force oracle, metamorphic checks and targeted probes.

Run from the disposable copy:
  DATABASE_URL=sqlite:////private/tmp/huce-audit-20261026/algo.db PYTHONPATH=apps/api \
    .venv/bin/python <this file> <evidence_dir>

Fixtures are built through the ORM (fixture construction only). Verdicts come from
independent_checker.py (stdlib sqlite3) and from the brute-force oracle below, which
re-implements the objective from its documented formula without product helpers.
"""
from __future__ import annotations

import itertools
import json
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import independent_checker as ic  # noqa: E402

from sqlalchemy import select  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.models.entities import (  # noqa: E402
    Assignment, ClassSection, ClassSession, Constraint, Course, Lecturer, LecturerCourseCapability, Seminar, Semester,
)
from app.optimization.solver import solve  # noqa: E402

DB_PATH = os.environ["DATABASE_URL"].replace("sqlite:///", "")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)
START = date(2026, 1, 1)


def reset():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def semester(db):
    s = Semester(name="AUDIT", department_name="D", start_date=START, end_date=date(2026, 6, 1), head_name="H")
    db.add(s); db.flush(); return s


def lecturer(db, code):
    item = Lecturer(code=code, canonical_name=code); db.add(item); db.flush(); return item


def course(db, code, name=None):
    item = Course(code=code, name=name or code); db.add(item); db.flush(); return item


def section(db, s, c, code, meetings, credits=3.0, **extra):
    item = ClassSection(semester_id=s.id, course_id=c.id, class_code=code, credits=credits, source_file="audit", source_sheet="s", source_row=0, **extra)
    db.add(item); db.flush()
    for weekday, sp, ep, weeks in meetings:
        db.add(ClassSession(class_id=item.id, weekday=weekday, start_period=sp, end_period=ep, room="R", raw_weeks="", active_weeks=list(weeks), source_row=0))
    db.flush(); return item


def cap(db, lec, crs, allowed=True, confirmed=True, source=None):
    db.add(LecturerCourseCapability(lecturer_id=lec.id, course_id=crs.id, allowed=allowed, confirmed=confirmed, source=source)); db.flush()


def rule(db, s, lec, kind, target, hardness="hard", weight=1.0):
    db.add(Constraint(semester_id=s.id, name=kind, constraint_type=kind, hardness=hardness, weight=weight, lecturer_id=lec.id if lec else None,
                      target=target, confirmed=True, active=True)); db.flush()


def run_solver(sid, limit=10, confirm=False):
    with SessionLocal() as db:
        run = solve(db, limit, confirm, sid)
        return run.id, run.status, run.score, run.summary


# ---------------------------------------------------------------- oracle

def oracle(sid):
    """Exhaustive optimum of the documented objective for a tiny instance."""
    con, sem, classes, sessions, caps, constraints, _ = ic.load(DB_PATH, sid)
    lecturers = [r[0] for r in con.execute("select id from lecturers order by id")]
    allowed = {(c["lecturer_id"], c["course_id"]) for c in caps if c["allowed"] and c["confirmed"]}
    ids = sorted(classes)
    slots = {cid: ic.class_slots(cid, sessions, sem) for cid in ids}
    cand = {}
    cap_only = {}
    soft_cost = {}
    for cid in ids:
        options = [l for l in lecturers if (l, classes[cid]["course_id"]) in allowed]
        cap_only[cid] = list(options)
        for c in constraints:
            if c["hardness"] != "hard":
                continue
            t = c["target"]
            hits = [s["weekday"] == t["weekday"] and any(s["start_period"] <= p <= s["end_period"] for p in t["periods"]) for s in sessions[cid]]
            if (c["constraint_type"] == "UNAVAILABLE" and any(hits)) or (c["constraint_type"] == "PREFERRED" and not all(hits)):
                options = [l for l in options if l != c["lecturer_id"]]
        cand[cid] = options
        for l in options:
            cost = 0
            for c in constraints:
                if c["lecturer_id"] != l or c["hardness"] != "soft":
                    continue
                t = c["target"]
                hits = [s["weekday"] == t["weekday"] and any(s["start_period"] <= p <= s["end_period"] for p in t["periods"]) for s in sessions[cid]]
                if c["constraint_type"] == "UNAVAILABLE" and any(hits):
                    cost += round(c["weight"] * 100)
                if c["constraint_type"] == "PREFERRED" and not all(hits):
                    cost += round(c["weight"] * 100)
            soft_cost[cid, l] = cost
    groups = {}
    for cid in ids:
        g = classes[cid]["merged_group_id"]
        if g and classes[cid]["merged_confirmed"]:
            groups.setdefault(g, []).append(cid)
    # Documented pre-solve guards: the run is blocked, not solved.
    # The product's readiness guard is capability-only (hard rules are applied later).
    if ids and all(not cap_only[cid] for cid in ids):
        return ("BLOCKED", "DATA_READINESS_FAILURE")
    for cid in ids:
        cls = classes[cid]
        if cls["locked_assignment"] and cls["assigned_lecturer_id"] and cls["assigned_lecturer_id"] not in cand[cid]:
            return ("BLOCKED", "LOCKED_ASSIGNMENT_INVALID")
    secondary = {cid for members in groups.values() for cid in members[1:]}
    capable = {l for cid in ids if cid not in secondary for l in cand[cid]}
    best = None
    for choice in itertools.product(*[[None, *cand[cid]] for cid in ids]):
        a = dict(zip(ids, choice))
        ok = True
        for cid in ids:
            cls = classes[cid]
            if cls["locked_assignment"] and cls["assigned_lecturer_id"] and a[cid] != cls["assigned_lecturer_id"]:
                ok = False; break
        if not ok:
            continue
        for members in groups.values():
            if len({a[m] for m in members}) > 1:
                ok = False; break
        if not ok:
            continue
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                if a[x] is not None and a[x] == a[y] and ic.collide(slots[x], slots[y]) and not ic.confirmed_merge(x, y, classes, sessions):
                    ok = False; break
            if not ok:
                break
        if not ok:
            continue
        unassigned = sum(1 for v in a.values() if v is None)
        load = {l: 0 for l in capable}
        for cid in ids:
            if cid not in secondary and a[cid] is not None:
                load[a[cid]] += int(classes[cid]["credits"] * 10)
        zero = sum(1 for l in capable if load[l] == 0)
        spread = (max(load.values()) - min(load.values())) if load else 0
        soft = sum(soft_cost[cid, a[cid]] for cid in ids if a[cid] is not None)
        value = unassigned * 1_000_000 + zero * 100_000 + spread * 1000 + soft
        if best is None or value < best[0]:
            best = (value, a, {"unassigned": unassigned, "zero": zero, "spread": spread, "soft": soft})
    return best


def random_instance(rng):
    reset()
    with SessionLocal() as db:
        s = semester(db)
        lecs = [lecturer(db, f"L{i}") for i in range(rng.randint(2, 3))]
        courses = [course(db, f"C{i}") for i in range(rng.randint(1, 2))]
        for l in lecs:
            for c in courses:
                if rng.random() < 0.7:
                    cap(db, l, c)
        week_sets = [[1, 2], [3, 4], [1, 2, 3, 4], [2, 3]]
        made = []
        for n in range(rng.randint(3, 6)):
            meeting = (rng.choice([2, 3]), *rng.choice([(1, 3), (4, 6)]), rng.choice(week_sets))
            made.append(section(db, s, rng.choice(courses), f"K{n}", [meeting], credits=rng.choice([2.0, 3.0])))
        if rng.random() < 0.3:
            twin_of = rng.choice(made)
            twin = section(db, s, db.get(Course, twin_of.course_id), "TWIN", [(m.weekday, m.start_period, m.end_period, m.active_weeks) for m in twin_of.sessions],
                           credits=twin_of.credits)
            for item in (twin_of, twin):
                item.merged_group_id = "G"; item.merged_confirmed = True; item.merge_status = "confirmed"
        for l in lecs:
            if rng.random() < 0.4:
                rule(db, s, l, rng.choice(["UNAVAILABLE", "PREFERRED"]), {"weekday": rng.choice([2, 3]), "periods": [rng.choice([1, 4])]},
                     hardness=rng.choice(["hard", "soft"]), weight=rng.choice([0.2, 0.5, 1.0]))
        if rng.random() < 0.3:
            target = rng.choice(made)
            capable = [c.lecturer_id for c in db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.course_id == target.course_id))]
            if capable:
                target.locked_assignment = True; target.assigned_lecturer_id = capable[0]; target.assignment_source = "MANUAL"
        db.commit()
        return s.id


def oracle_suite(count=150, seed=20261026):
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        sid = random_instance(rng)
        expected = oracle(sid)
        run_id, status, score, summary = run_solver(sid)
        issues, assigned = ic.check(DB_PATH, sid, run_id) if status in {"optimal", "feasible"} else ([], {})
        row = {"case": index, "status": status, "solver_score": score, "oracle_score": expected[0] if expected else None,
               "oracle_parts": expected[2] if expected and len(expected) > 2 else None,
               "solver_parts": (summary.get("experiment") or {}).get("objective_components"), "checker_issues": issues}
        if expected is None:
            row["verdict"] = "PASS" if status in {"blocked", "infeasible"} else "FAIL"
        elif expected[0] == "BLOCKED":
            row["oracle_score"] = expected[1]; row["oracle_parts"] = None
            row["verdict"] = "PASS" if status == "blocked" and summary.get("code") == expected[1] else "FAIL"
        else:
            row["verdict"] = "PASS" if status == "optimal" and round(score) == expected[0] and not issues else "FAIL"
        rows.append(row)
    return rows


# ---------------------------------------------------------------- probes

def probe_forbidden_course_scope():
    """Hard FORBIDDEN_ASSIGNMENT on a course must hold for every class of that course."""
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C")
        cap(db, a, c); cap(db, b, c)
        k1 = section(db, s, c, "K1", [(2, 1, 3, [1, 2])])
        section(db, s, c, "K2", [(3, 1, 3, [1, 2])])
        # A is hard-busy on Monday morning, so A is not a candidate for K1 only.
        rule(db, s, a, "UNAVAILABLE", {"weekday": 2, "periods": [1, 2, 3]})
        rule(db, s, a, "FORBIDDEN_ASSIGNMENT", {"course_id": c.id})
        # B is busy Tuesday morning, so the cheapest way to cover K2 is A — which is forbidden.
        rule(db, s, b, "UNAVAILABLE", {"weekday": 3, "periods": [1, 2, 3]})
        db.commit(); sid = s.id; aid = a.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    hit = [i for i in issues if i[0] == "HARD_FORBIDDEN_VIOLATED"]
    return {"id": "ALG-FORBIDDEN-COURSE", "expected": "A never teaches course C; K2 unassigned", "status": status,
            "assigned": assigned, "invalid_constraints": summary.get("invalid_constraints"), "checker": issues,
            "verdict": "FAIL" if hit else "PASS", "lecturer_A": aid}


def probe_half_confirmed_merge():
    """A pending member must not inherit the no-overlap exemption of a confirmed member."""
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C"); cap(db, a, c)
        m = [(2, 1, 3, [1, 2])]
        k1 = section(db, s, c, "K1", m, merged_group_id="G", merged_confirmed=True, merge_status="confirmed")
        k2 = section(db, s, c, "K2", m, merged_group_id="G", merged_confirmed=False, merge_status="candidate")
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    hit = [i for i in issues if i[0] == "DOUBLE_BOOKING"]
    return {"id": "ALG-HALF-MERGE", "expected": "only one of K1/K2 assigned to A (merge not confirmed for K2)", "status": status,
            "assigned": assigned, "checker": issues, "verdict": "FAIL" if hit else "PASS"}


def probe_min_classes_without_candidates():
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C"); cap(db, a, c)
        section(db, s, c, "K1", [(2, 1, 3, [1])])
        rule(db, s, b, "MIN_CLASSES", {"min": 1})
        db.commit(); sid = s.id
    try:
        run_id, status, score, summary = run_solver(sid)
        return {"id": "ALG-MIN-NO-CAND", "expected": "blocked/infeasible with explanation (B can never reach 1 class)", "status": status,
                "summary_code": summary.get("code"), "verdict": "PASS" if status in {"infeasible", "blocked", "model_invalid"} else "FAIL"}
    except Exception as exc:  # noqa: BLE001
        return {"id": "ALG-MIN-NO-CAND", "expected": "blocked/infeasible with explanation", "status": "EXCEPTION",
                "error": f"{type(exc).__name__}: {exc}", "verdict": "FAIL"}


def probe_objective_priority():
    """Can soft cost ever beat completeness? Search the allowed weight range (0..1)."""
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C"); cap(db, a, c)
        weeks = list(range(1, 16))
        section(db, s, c, "K1", [(2, 1, 1, weeks)], credits=3)
        section(db, s, c, "K2", [(2, 15, 15, weeks)], credits=3)
        rule(db, s, a, "PREFER_CONSECUTIVE_PERIODS", {}, hardness="soft", weight=1.0)
        rule(db, s, a, "UNAVAILABLE", {"weekday": 2, "periods": [15]}, hardness="soft", weight=1.0)
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid, limit=20)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    comps = (summary.get("experiment") or {}).get("objective_components")
    return {"id": "ALG-PRIORITY", "expected": "both classes assigned (completeness dominates soft)", "status": status, "assigned": assigned,
            "components": comps, "verdict": "PASS" if len(assigned) == 2 else "FAIL",
            "note": "gap penalty = weight*100 per empty period per week per day; 13 gaps x 15 weeks x 100 = 19,500 < 1,000,000"}


def probe_spread_vs_unassigned():
    """Disparity growth from one class is credits*10*1000; check credits large enough to invert."""
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C"); d = course(db, "D")
        cap(db, a, c); cap(db, a, d); cap(db, b, d)
        section(db, s, c, "BIG", [(2, 1, 3, [1])], credits=150.0)
        section(db, s, d, "SMALL", [(3, 1, 3, [1])], credits=1.0)
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    return {"id": "ALG-SPREAD-INVERSION", "expected": "BIG assigned to A (only candidate)", "status": status, "assigned": assigned,
            "components": (summary.get("experiment") or {}).get("objective_components"),
            "verdict": "PASS" if len(assigned) == 2 else "FAIL",
            "note": "weighted sum: 150 credits -> spread +1500 units x 1000 = 1.5e6 > 1e6 unassigned weight"}


def probe_name_bridge():
    """Two different course codes sharing a name: capability on one leaks to the other."""
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A")
        c1 = course(db, "MATH-1", "Đồ án tốt nghiệp"); c2 = course(db, "ARCH-9", "Đồ án tốt nghiệp")
        cap(db, a, c1)
        section(db, s, c2, "K1", [(2, 1, 3, [1])])
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    return {"id": "ALG-NAME-BRIDGE", "expected": "policy decision: unassigned unless equivalence approved", "status": status, "assigned": assigned,
            "checker": issues, "verdict": "FAIL" if any(i[0] == "NO_DIRECT_CAPABILITY" for i in issues) else "PASS"}


def probe_max_days_week_semantics():
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C"); cap(db, a, c)
        section(db, s, c, "MON-W1-7", [(2, 1, 3, list(range(1, 8)))])
        section(db, s, c, "TUE-W8-15", [(3, 1, 3, list(range(8, 16)))])
        rule(db, s, a, "MAX_DAYS_PER_WEEK", {"max": 1})
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    return {"id": "ALG-MAX-DAYS-WEEK", "expected": "both assigned: each calendar week has only one teaching day", "status": status,
            "assigned": assigned, "verdict": "PASS" if len(assigned) == 2 else "FAIL"}


def probe_bottleneck():
    reset()
    with SessionLocal() as db:
        s = semester(db); c = course(db, "C")
        lecs = [lecturer(db, f"L{i}") for i in range(7)]
        for l in lecs:
            cap(db, l, c)
        for n in range(8):
            section(db, s, c, f"K{n}", [(4, 4, 6, [1, 2, 3])], merged_group_id="G", merged_confirmed=False, merge_status="candidate")
        db.commit(); sid = s.id
    run_id, status, score, summary = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    return {"id": "ALG-BOTTLENECK-8x7", "expected": "7 assigned, 1 unassigned (Hall bound: 8 classes, 7 lecturers, one slot)", "status": status,
            "assigned_count": len(assigned), "checker": issues, "verdict": "PASS" if len(assigned) == 7 and not issues else "FAIL"}


def probe_hypothetical_mutation():
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C")
        cap(db, a, c, allowed=True, confirmed=True, source="HYPOTHETICAL_ALL")
        section(db, s, c, "K1", [(2, 1, 3, [1])])
        db.commit(); sid = s.id
    run_solver(sid)
    import sqlite3
    row = sqlite3.connect(DB_PATH).execute("select allowed, confirmed from lecturer_course_capabilities").fetchone()
    return {"id": "ALG-SOLVE-MUTATES-CAPS", "expected": "solve is read-only on capability catalog", "after": row,
            "verdict": "FAIL" if tuple(row) != (1, 1) else "PASS"}


# ---------------------------------------------------------------- metamorphic

def metamorphic():
    results = []
    # 1. Row order must not change the optimum.
    scores = []
    for order in ([0, 1, 2, 3, 4], [4, 2, 0, 3, 1]):
        reset()
        with SessionLocal() as db:
            s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C"); cap(db, a, c); cap(db, b, c)
            specs = [(2, 1, 3, [1, 2]), (2, 1, 3, [2, 3]), (3, 4, 6, [1]), (2, 1, 3, [5]), (3, 4, 6, [1, 2])]
            for idx in order:
                section(db, s, c, f"K{idx}", [specs[idx]], credits=2 + idx % 2)
            db.commit(); sid = s.id
        scores.append(run_solver(sid)[2])
    results.append({"id": "META-ORDER", "scores": scores, "verdict": "PASS" if scores[0] == scores[1] else "FAIL"})
    # 2. Disjoint weeks never collide.
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C"); cap(db, a, c)
        section(db, s, c, "ODD", [(2, 1, 3, [1, 3, 5])]); section(db, s, c, "EVEN", [(2, 1, 3, [2, 4, 6])])
        db.commit(); sid = s.id
    run_id, status, *_ = run_solver(sid)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    results.append({"id": "META-DISJOINT-WEEKS", "assigned": len(assigned), "verdict": "PASS" if len(assigned) == 2 and not issues else "FAIL"})
    # 3. Unconfirmed merge must not bypass collisions.
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); c = course(db, "C"); cap(db, a, c)
        for n in range(2):
            section(db, s, c, f"K{n}", [(2, 1, 3, [1])], merged_group_id="G", merged_confirmed=False, merge_status="candidate")
        db.commit(); sid = s.id
    run_id, status, *_ = run_solver(sid, confirm=False)
    issues, assigned = ic.check(DB_PATH, sid, run_id)
    results.append({"id": "META-UNCONFIRMED-MERGE", "assigned": len(assigned), "verdict": "PASS" if len(assigned) == 1 and not issues else "FAIL"})
    # 4. Locks survive re-solve; unlock lets the solver reconsider.
    reset()
    with SessionLocal() as db:
        s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C"); cap(db, a, c); cap(db, b, c)
        k = section(db, s, c, "K", [(2, 1, 3, [1])]); section(db, s, c, "K2", [(3, 1, 3, [1])])
        rule(db, s, a, "PREFERRED", {"weekday": 3, "periods": [1]}, hardness="soft", weight=1.0)
        k.locked_assignment = True; k.assigned_lecturer_id = a.id; k.assignment_source = "MANUAL"
        db.commit(); sid = s.id; kid = k.id; aid = a.id
    first = run_solver(sid); second = run_solver(sid)
    keep = [ic.check(DB_PATH, sid, r[0])[1].get(kid) for r in (first, second)]
    results.append({"id": "META-LOCK-RESOLVE", "lecturer_each_run": keep, "verdict": "PASS" if keep == [aid, aid] else "FAIL"})
    # 5. Adding a capability cannot make the proven optimum worse.
    pair = []
    for extra in (False, True):
        reset()
        with SessionLocal() as db:
            s = semester(db); a = lecturer(db, "A"); b = lecturer(db, "B"); c = course(db, "C"); cap(db, a, c)
            if extra:
                cap(db, b, c)
            for n in range(3):
                section(db, s, c, f"K{n}", [(2, 1, 3, [1])])
            db.commit(); sid = s.id
        _, status, score, _ = run_solver(sid)
        pair.append((status, score))
    results.append({"id": "META-MONOTONE-CAPABILITY", "runs": pair,
                    "verdict": "PASS" if all(p[0] == "optimal" for p in pair) and pair[1][1] <= pair[0][1] else "FAIL"})
    return results


def determinism():
    reset()
    rng = random.Random(7)
    with SessionLocal() as db:
        s = semester(db); c = course(db, "C")
        lecs = [lecturer(db, f"L{i}") for i in range(6)]
        for l in lecs:
            cap(db, l, c)
        for n in range(30):
            section(db, s, c, f"K{n}", [(rng.choice([2, 3, 4]), *rng.choice([(1, 3), (4, 6)]), [1, 2, 3])], credits=rng.choice([2.0, 3.0]))
        db.commit(); sid = s.id
    plans = []
    for _ in range(3):
        run_id, status, score, _ = run_solver(sid)
        plans.append((status, score, tuple(sorted(ic.check(DB_PATH, sid, run_id)[1].items()))))
    distinct = len({p[2] for p in plans})
    return {"id": "DETERMINISM-3RUNS", "scores": [p[1] for p in plans], "distinct_plans": distinct,
            "verdict": "INFO", "note": "same objective expected; different plans = co-optimal reshuffle"}


if __name__ == "__main__":
    started = time.time()
    report = {"probes": [], "metamorphic": [], "oracle": []}
    for fn in (probe_forbidden_course_scope, probe_half_confirmed_merge, probe_min_classes_without_candidates, probe_objective_priority,
               probe_spread_vs_unassigned, probe_name_bridge, probe_max_days_week_semantics, probe_bottleneck, probe_hypothetical_mutation):
        report["probes"].append(fn())
    report["metamorphic"] = metamorphic()
    report["determinism"] = determinism()
    report["oracle"] = oracle_suite()
    report["elapsed_seconds"] = time.time() - started
    (OUT / "algo-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"probes": [(p["id"], p["verdict"]) for p in report["probes"]],
                      "metamorphic": [(m["id"], m["verdict"]) for m in report["metamorphic"]],
                      "determinism": report["determinism"],
                      "oracle_pass": sum(r["verdict"] == "PASS" for r in report["oracle"]), "oracle_total": len(report["oracle"])},
                     ensure_ascii=False, indent=1, default=str))
