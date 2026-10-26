"""Independent post-solve checker.

Reads the SQLite file with the stdlib sqlite3 module only. It does NOT import
any product module (no app.optimization, no app.services), so its verdicts do
not reuse solver helpers. Dated occurrences, overlap, capability and merge
rules are re-implemented here from the written business rules:

* week 1 starts on the Monday of the week containing semester.start_date;
* a meeting occurs on monday + 7*(week-1) + (weekday-2) days, inside the
  meeting's own start/end dates when those exist;
* two classes collide when they share a date and their period ranges intersect;
* a collision is acceptable only for a CONFIRMED merge: same merged_group_id,
  both merged_confirmed, neither rejected, identical meeting sets;
* a lecturer may teach a course only with a direct capability row that is
  allowed, confirmed and not HYPOTHETICAL_ALL, or an approved MANUAL_OVERRIDE lock.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta


def _d(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load(db_path: str, semester_id: int):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    sem = con.execute("select * from semesters where id=?", (semester_id,)).fetchone()
    classes = {r["id"]: dict(r) for r in con.execute("select * from classes where semester_id=?", (semester_id,))}
    sessions = defaultdict(list)
    for r in con.execute("select * from sessions where class_id in (select id from classes where semester_id=?)", (semester_id,)):
        row = dict(r)
        row["active_weeks"] = json.loads(row["active_weeks"] or "[]")
        sessions[row["class_id"]].append(row)
    caps = [dict(r) for r in con.execute("select * from lecturer_course_capabilities")]
    constraints = [dict(r) for r in con.execute("select * from constraints where semester_id=? and active=1 and confirmed=1", (semester_id,))]
    for c in constraints:
        c["target"] = json.loads(c["target"] or "{}")
    seminars = [dict(r) for r in con.execute("select * from seminars where semester_id=?", (semester_id,))]
    for s in seminars:
        s["members"] = json.loads(s["members"] or "[]")
        s["alternatives"] = json.loads(s["alternatives"] or "[]")
    return con, dict(sem), classes, sessions, caps, constraints, seminars


def occurrences(session, sem):
    anchor = _d(sem["start_date"])
    monday = anchor - timedelta(days=anchor.weekday())
    lo, hi = _d(session.get("start_date")), _d(session.get("end_date"))
    out = set()
    for week in set(session["active_weeks"] or []):
        actual = monday + timedelta(days=7 * (week - 1) + session["weekday"] - 2)
        if lo and actual < lo:
            continue
        if hi and actual > hi:
            continue
        out.add((actual, session["start_period"], session["end_period"]))
    return out


def class_slots(class_id, sessions, sem):
    slots = set()
    for s in sessions[class_id]:
        slots |= occurrences(s, sem)
    return slots


def collide(a, b):
    return any(d1 == d2 and not (e1 < s2 or e2 < s1) for d1, s1, e1 in a for d2, s2, e2 in b)


def _signature(class_id, sessions):
    return sorted((s["weekday"], s["start_period"], s["end_period"], str(s.get("start_date")), str(s.get("end_date")), tuple(sorted(s["active_weeks"] or [])))
                  for s in sessions[class_id])


def confirmed_merge(a, b, classes, sessions):
    ca, cb = classes[a], classes[b]
    return bool(ca["merged_group_id"] and ca["merged_group_id"] == cb["merged_group_id"]
                and ca["merged_confirmed"] and cb["merged_confirmed"]
                and ca["merge_status"] != "rejected" and cb["merge_status"] != "rejected"
                and _signature(a, sessions) == _signature(b, sessions))


def run_assignments(con, run_id):
    rows = [dict(r) for r in con.execute("select * from assignments where run_id=?", (run_id,))]
    return rows


def check(db_path: str, semester_id: int, run_id: int, *, allow_provisional=False, snapshot_classes=None):
    """Return a list of (code, detail) violations for one persisted run."""
    con, sem, classes, sessions, caps, constraints, seminars = load(db_path, semester_id)
    if snapshot_classes:
        classes = snapshot_classes
    rows = run_assignments(con, run_id)
    issues = []
    by_class = defaultdict(list)
    for r in rows:
        by_class[r["class_id"]].append(r["lecturer_id"])
        if r["class_id"] not in classes:
            issues.append(("FOREIGN_CLASS", r["class_id"]))
    for cid, lids in by_class.items():
        if len(lids) > 1:
            issues.append(("MULTIPLE_LECTURERS", cid, lids))
    assigned = {cid: lids[0] for cid, lids in by_class.items()}

    allowed = {(c["lecturer_id"], c["course_id"]) for c in caps
               if c["allowed"] and (c["confirmed"] or allow_provisional) and (c["source"] or "") != "HYPOTHETICAL_ALL"}
    forbidden = {(c["lecturer_id"], c["course_id"]) for c in caps if not c["allowed"]}
    for cid, lid in assigned.items():
        cls = classes[cid]
        override = cls["locked_assignment"] and cls["assignment_source"] == "MANUAL_OVERRIDE" and cls["assigned_lecturer_id"] == lid
        if (lid, cls["course_id"]) in forbidden and not override:
            issues.append(("FORBIDDEN_CAPABILITY", cid, lid))
        elif (lid, cls["course_id"]) not in allowed and not override:
            issues.append(("NO_DIRECT_CAPABILITY", cid, lid))
        if cls["locked_assignment"] and cls["assigned_lecturer_id"] and cls["assigned_lecturer_id"] != lid:
            issues.append(("LOCK_CHANGED", cid, cls["assigned_lecturer_id"], lid))
    for cid, cls in classes.items():
        if cls["locked_assignment"] and cls["assigned_lecturer_id"] and cid not in assigned:
            issues.append(("LOCK_DROPPED", cid))

    slots = {cid: class_slots(cid, sessions, sem) for cid in classes}
    ids = sorted(assigned)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if assigned[a] != assigned[b]:
                if confirmed_merge(a, b, classes, sessions):
                    issues.append(("CONFIRMED_MERGE_SPLIT", a, b))
                continue
            if collide(slots[a], slots[b]) and not confirmed_merge(a, b, classes, sessions):
                issues.append(("DOUBLE_BOOKING", a, b, assigned[a]))

    for c in constraints:
        kind = (c["constraint_type"] or "").upper()
        t = c["target"]
        lid = c["lecturer_id"]
        if c["hardness"] != "hard":
            continue
        mine = [cid for cid, l in assigned.items() if l == lid]
        if kind in {"UNAVAILABLE", "BUSY_EVENT"}:
            for cid in mine:
                for s in sessions[cid]:
                    if t.get("weekday") is not None and s["weekday"] != t["weekday"]:
                        continue
                    periods = t.get("periods") or []
                    if periods and not any(s["start_period"] <= p <= s["end_period"] for p in periods):
                        continue
                    weeks = set(t.get("weeks") or [])
                    if weeks and not weeks & set(s["active_weeks"]):
                        continue
                    issues.append(("HARD_UNAVAILABLE_VIOLATED", cid, lid, c["id"]))
        elif kind == "FORBIDDEN_ASSIGNMENT":
            for cid in mine:
                if t.get("class_id") == cid or (t.get("class_id") is None and t.get("course_id") == classes[cid]["course_id"]):
                    issues.append(("HARD_FORBIDDEN_VIOLATED", cid, lid, c["id"]))
        elif kind == "REQUIRED_ASSIGNMENT":
            if t.get("class_id") in classes and assigned.get(t["class_id"]) != lid:
                issues.append(("HARD_REQUIRED_VIOLATED", t["class_id"], lid, c["id"]))
        elif kind == "MAX_CLASSES" and isinstance(t.get("max"), int) and len(mine) > t["max"]:
            issues.append(("HARD_MAX_CLASSES_VIOLATED", lid, len(mine), t["max"]))
        elif kind == "MIN_CLASSES" and isinstance(t.get("min"), int) and len(mine) < t["min"]:
            issues.append(("HARD_MIN_CLASSES_VIOLATED", lid, len(mine), t["min"]))
    return issues, assigned


def workload(assigned, classes, sessions, participating):
    """Credit load counted once per confirmed merge group, as the business rule states."""
    seen_groups = set()
    load = defaultdict(int)
    for cid, lid in sorted(assigned.items()):
        cls = classes[cid]
        key = cls["merged_group_id"] if (cls["merged_group_id"] and cls["merged_confirmed"]) else None
        if key and (key, lid) in seen_groups:
            continue
        if key:
            seen_groups.add((key, lid))
        load[lid] += int(cls["credits"] * 10)
    return {lid: load.get(lid, 0) for lid in participating}
