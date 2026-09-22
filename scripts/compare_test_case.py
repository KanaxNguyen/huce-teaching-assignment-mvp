#!/usr/bin/env python3
"""
scripts/compare_test_case.py

Independent Invariant Checker and Test Oracle for HUCE Teaching Assignment Test Fixtures.
Usage:
    python scripts/compare_test_case.py --case test_fixtures/TC07_alternating_weeks_no_collision
    python scripts/compare_test_case.py --case test_fixtures/TC02_hard_unavailable --actual actual_result.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import openpyxl

# Add apps/api to path if available
api_path = Path(__file__).resolve().parent.parent / "huce-teaching-assignment-mvp" / "apps" / "api"
if not api_path.exists():
    api_path = Path(__file__).resolve().parent.parent / "apps" / "api"
if not api_path.exists():
    api_path = Path("/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp/apps/api")
if api_path.exists():
    sys.path.insert(0, str(api_path))


def recalculate_collisions(assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Independently recalculates timetable collisions.
    A true collision exists ONLY when:
    same lecturer AND same weekday AND overlapping periods AND overlapping active weeks.
    """
    collisions = []
    by_lecturer = {}
    for a in assignments:
        lec = a.get("lecturer")
        if not lec:
            continue
        by_lecturer.setdefault(lec, []).append(a)

    for lec, items in by_lecturer.items():
        n = len(items)
        for i in range(n):
            for j in range(i + 1, n):
                a1, a2 = items[i], items[j]
                for s1 in a1.get("sessions", []):
                    for s2 in a2.get("sessions", []):
                        if s1["weekday"] != s2["weekday"]:
                            continue
                        # Period overlap
                        if s1["end_period"] < s2["start_period"] or s2["end_period"] < s1["start_period"]:
                            continue
                        # Active weeks overlap
                        w1 = set(s1.get("active_weeks", []))
                        w2 = set(s2.get("active_weeks", []))
                        overlap_weeks = sorted(w1.intersection(w2))
                        if overlap_weeks:
                            collisions.append({
                                "lecturer": lec,
                                "class_1": a1.get("class_code"),
                                "class_2": a2.get("class_code"),
                                "weekday": s1["weekday"],
                                "periods_1": f"{s1['start_period']}-{s1['end_period']}",
                                "periods_2": f"{s2['start_period']}-{s2['end_period']}",
                                "overlapping_weeks": overlap_weeks,
                            })
    return collisions


def recalculate_hard_violations(assignments: List[Dict[str, Any]], hard_constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Independently checks if any assigned class overlaps a HARD UNAVAILABLE constraint.
    """
    violations = []
    for a in assignments:
        lec = a.get("lecturer")
        if not lec:
            continue
        for s in a.get("sessions", []):
            for hc in hard_constraints:
                if hc.get("lecturer") != lec:
                    continue
                if hc.get("type") not in ("UNAVAILABLE", "HARD_UNAVAILABLE"):
                    continue
                # Check weekday
                scope = hc.get("day_scope")
                target_days = (
                    {2, 3, 4, 5, 6} if scope == "ALL_WEEKDAYS"
                    else {2, 3, 4, 5, 6, 7, 8} if scope == "ALL_DAYS"
                    else {int(scope[1:])} if scope and scope.startswith("T") and scope[1:].isdigit()
                    else set()
                )
                if s["weekday"] not in target_days:
                    continue
                # Check periods
                c_periods = set(hc.get("periods", []))
                s_periods = set(range(s["start_period"], s["end_period"] + 1))
                overlap_periods = sorted(c_periods.intersection(s_periods))
                if overlap_periods:
                    violations.append({
                        "lecturer": lec,
                        "class_code": a.get("class_code"),
                        "weekday": s["weekday"],
                        "violated_periods": overlap_periods,
                        "constraint": hc
                    })
    return violations


def recalculate_capability_violations(assignments: List[Dict[str, Any]], capabilities_by_lec: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """
    Independently checks if any assigned class is assigned to a lecturer without capability.
    """
    violations = []
    for a in assignments:
        lec = a.get("lecturer")
        if not lec:
            continue
        course_code = a.get("course_code")
        allowed_courses = capabilities_by_lec.get(lec, [])
        if course_code and course_code not in allowed_courses:
            violations.append({
                "lecturer": lec,
                "class_code": a.get("class_code"),
                "course_code": course_code,
                "allowed_courses": allowed_courses
            })
    return violations


def run_test_case_in_memory(case_dir: Path) -> Dict[str, Any]:
    """
    Executes the test case end-to-end through the HUCE parser and solver using an in-memory database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base
    from app.models.entities import (
        Semester, Lecturer, Course, LecturerCourseCapability,
        ClassSection, ClassSession, Constraint, Assignment, OptimizationRun
    )
    from app.parsers.schedule import parse_schedule
    from app.parsers.preferences import parse_preference_workbook
    from app.optimization.solver import solve

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        # 1. Setup Semester
        sem = Semester(
            name="Test Semester",
            department_name="Bộ môn Toán học",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 1, 24),
            head_name="Phạm Đức Thoan"
        )
        db.add(sem)
        db.flush()

        # 2. Load fixture meta
        meta_file = case_dir / "fixture_meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        caps_meta = meta.get("capabilities", {})
        locked_classes = set(meta.get("locked", []))

        # 3. Parse and insert Preferences
        pref_file = case_dir / "preference_input.xlsx"
        parsed_prefs = parse_preference_workbook(pref_file, semester_start=sem.start_date, semester_end=sem.end_date)

        lecturer_map = {}
        for draft in parsed_prefs.drafts:
            code = draft.lecturer_code
            name = draft.canonical_name
            if code and code not in lecturer_map:
                lec = Lecturer(code=code, canonical_name=name)
                db.add(lec)
                db.flush()
                lecturer_map[code] = lec

        # Add constraints for confirmed drafts
        type_map = {
            "UNAVAILABLE": "unavailable",
            "AVOID_PERIOD": "avoid",
            "PREFERRED_PERIOD": "prefer_period",
            "PREFERRED_DAYS": "preferred_days",
            "AVOID_DAYS": "avoid_days",
            "PREFER_LOW_WORKLOAD": "prefer_low_workload",
            "PREFER_COMPACT_SCHEDULE": "prefer_compact_schedule",
            "PREFER_CONSECUTIVE_PERIODS": "prefer_consecutive_periods",
            "MIN_FREE_MORNING_PER_WEEK": "min_free_morning_per_week",
            "MIN_CLASSES": "min_classes",
            "MAX_CLASSES": "max_classes",
            "MAX_SESSIONS_PER_DAY": "max_sessions_per_day",
            "MAX_DAYS_PER_WEEK": "max_days_per_week",
            "REQUIRED_ASSIGNMENT": "required_assignment",
            "FORBIDDEN_ASSIGNMENT": "forbidden_assignment",
            "SEMINAR_COMMITMENT": "seminar",
        }
        for draft in parsed_prefs.drafts:
            lec = lecturer_map.get(draft.lecturer_code)
            if not lec:
                continue
            c = Constraint(
                semester_id=sem.id,
                lecturer_id=lec.id,
                name=f"{draft.constraint_type}_{draft.day_scope}",
                constraint_type=type_map.get(draft.constraint_type, draft.constraint_type),
                hardness=draft.hardness.lower(),
                weight=draft.weight,
                target=draft.target,
                confirmed=True,
                active=True,
            )
            db.add(c)
        db.flush()

        # 4. Parse and insert Timetable
        tt_file = case_dir / "timetable_input.xlsx"
        parsed_sched = parse_schedule(tt_file)

        course_map = {}
        section_map = {}
        for pc in parsed_sched.classes:
            if pc.course_code not in course_map:
                co = Course(code=pc.course_code, name=pc.course_name)
                db.add(co)
                db.flush()
                course_map[pc.course_code] = co

            is_locked = pc.class_code in locked_classes
            assigned_id = None
            if is_locked and pc.lecturer_code and pc.lecturer_code in lecturer_map:
                assigned_id = lecturer_map[pc.lecturer_code].id

            cs = ClassSection(
                semester_id=sem.id,
                course_id=course_map[pc.course_code].id,
                class_code=pc.class_code,
                credits=pc.credits,
                locked_assignment=is_locked,
                assigned_lecturer_id=assigned_id,
                source_file="timetable_input.xlsx",
                source_sheet="Schedule",
                source_row=pc.source_row
            )
            db.add(cs)
            db.flush()
            section_map[pc.class_code] = cs

            for s in pc.sessions:
                sess = ClassSession(
                    class_id=cs.id,
                    weekday=s.weekday,
                    start_period=s.start_period,
                    end_period=s.end_period,
                    room=s.room,
                    raw_weeks=s.raw_weeks,
                    active_weeks=s.active_weeks,
                    source_row=s.source_row
                )
                db.add(sess)
        db.flush()

        # 5. Insert Capabilities from meta
        for code, courses in caps_meta.items():
            lec = lecturer_map.get(code)
            if not lec:
                continue
            for ccode in courses:
                co = course_map.get(ccode)
                if co:
                    cap = LecturerCourseCapability(
                        lecturer_id=lec.id,
                        course_id=co.id,
                        confirmed=True,
                        allowed=True,
                        source="CONFIRMED_AUDIT"
                    )
                    db.add(cap)
        db.commit()

        # 6. Run Solver
        run = solve(db, time_limit_seconds=10, confirm_merged=False, semester_id=sem.id)

        # 7. Collect Actual Assignments
        actual_assignments = []
        assigned_count = 0
        unassigned_count = 0

        for pc in parsed_sched.classes:
            cs = section_map[pc.class_code]
            asg = db.query(Assignment).filter(Assignment.run_id == run.id, Assignment.class_id == cs.id).first()
            assigned_lec_name = None
            if asg:
                lec_obj = db.get(Lecturer, asg.lecturer_id)
                assigned_lec_name = lec_obj.canonical_name if lec_obj else None
                assigned_count += 1
            else:
                unassigned_count += 1

            actual_assignments.append({
                "class_code": pc.class_code,
                "course_code": pc.course_code,
                "course_name": pc.course_name,
                "lecturer": assigned_lec_name,
                "status": "ASSIGNED" if assigned_lec_name else "UNASSIGNED",
                "sessions": [
                    {
                        "weekday": s.weekday,
                        "start_period": s.start_period,
                        "end_period": s.end_period,
                        "active_weeks": s.active_weeks
                    }
                    for s in pc.sessions
                ]
            })

        unassigned_diag = run.summary.get("unassigned", [])

        return {
            "total_groups": len(parsed_sched.classes),
            "actual_assigned": assigned_count,
            "actual_unassigned": unassigned_count,
            "assignments": actual_assignments,
            "unassigned_diagnostics": unassigned_diag,
            "solver_status": run.status,
            "objective_value": run.score
        }


def compare(case_dir_str: str, actual_file_str: str = None) -> Tuple[bool, List[str]]:
    case_dir = Path(case_dir_str).resolve()
    exp_file = case_dir / "expected_result.json"
    if not exp_file.exists():
        return False, [f"Missing expected_result.json in {case_dir}"]

    expected = json.loads(exp_file.read_text(encoding="utf-8"))

    if actual_file_str:
        actual_path = Path(actual_file_str).resolve()
        actual = json.loads(actual_path.read_text(encoding="utf-8"))
    else:
        actual = run_test_case_in_memory(case_dir)

    mismatches = []

    # 1. Compare total groups
    if actual["total_groups"] != expected["total_groups"]:
        mismatches.append(f"Total groups mismatch: Expected {expected['total_groups']}, got {actual['total_groups']}")

    # 2. Compare assigned count
    if actual["actual_assigned"] != expected["expected_assigned"]:
        mismatches.append(f"Assigned count mismatch: Expected {expected['expected_assigned']}, got {actual['actual_assigned']}")

    # 3. Compare unassigned count
    if actual["actual_unassigned"] != expected["expected_unassigned"]:
        mismatches.append(f"Unassigned count mismatch: Expected {expected['expected_unassigned']}, got {actual['actual_unassigned']}")

    # 4. Independent Collision Check
    collisions = recalculate_collisions(actual["assignments"])
    if len(collisions) != expected.get("expected_collisions", 0):
        mismatches.append(f"Collision count mismatch: Expected {expected.get('expected_collisions', 0)}, got {len(collisions)}: {collisions}")

    # 5. Independent Hard Violations Check
    pref_wb = openpyxl.load_workbook(case_dir / "preference_input.xlsx", data_only=True)
    pref_ws = pref_wb.active
    hard_rules = []
    for row in pref_ws.iter_rows(min_row=2, values_only=True):
        if row and len(row) >= 10 and str(row[9] or "").upper() == "HARD":
            start_p = int(row[5]) if row[5] not in (None, "") else None
            end_p = int(row[6]) if row[6] not in (None, "") else None
            periods = list(range(start_p, end_p + 1)) if start_p and end_p else []
            hard_rules.append({
                "lecturer": row[1],
                "type": row[3],
                "day_scope": row[4],
                "periods": periods
            })

    hard_viols = recalculate_hard_violations(actual["assignments"], hard_rules)
    if len(hard_viols) != expected.get("expected_hard_violations", 0):
        mismatches.append(f"HARD violations mismatch: Expected {expected.get('expected_hard_violations', 0)}, got {len(hard_viols)}: {hard_viols}")

    # 6. Independent Capability Check
    meta_file = case_dir / "fixture_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        code_to_name = {
            "00187": "Phạm Đức Thoan",
            "00172": "Lê Viết Cường",
            "00173": "Nguyễn Bằng Giang",
            "00957": "Vũ Thị Hương Giang"
        }
        caps_by_name = {code_to_name.get(k, k): v for k, v in meta.get("capabilities", {}).items()}
        cap_viols = recalculate_capability_violations(actual["assignments"], caps_by_name)
        if len(cap_viols) != expected.get("expected_capability_violations", 0):
            mismatches.append(f"Capability violations mismatch: Expected {expected.get('expected_capability_violations', 0)}, got {len(cap_viols)}: {cap_viols}")

    # 7. Exact assignments check
    actual_asg_map = {a["class_code"]: a.get("lecturer") for a in actual["assignments"]}
    for exact in expected.get("exact_assignments", []):
        ccode = exact["class_code"]
        exp_lec = exact["lecturer"]
        act_lec = actual_asg_map.get(ccode)
        if act_lec != exp_lec:
            mismatches.append(f"Exact assignment mismatch on class {ccode}: Expected '{exp_lec}', got '{act_lec}'")

    # 8. Unassigned checks
    actual_unassigned_codes = {a["class_code"] for a in actual["assignments"] if not a.get("lecturer")}
    for un in expected.get("unassigned", []):
        ccode = un.get("class_code")
        one_of = un.get("one_of")
        if one_of:
            if not any(c in actual_unassigned_codes for c in one_of):
                mismatches.append(f"Expected at least one of classes {one_of} to be unassigned, but all were assigned")
        elif ccode:
            if ccode not in actual_unassigned_codes:
                mismatches.append(f"Expected unassigned class {ccode} was assigned to '{actual_asg_map.get(ccode)}'")

    passed = len(mismatches) == 0
    return passed, mismatches


def main():
    parser = argparse.ArgumentParser(description="HUCE Test Case Comparison Tool")
    parser.add_argument("--case", required=True, help="Path to test case directory")
    parser.add_argument("--actual", required=False, help="Path to actual result JSON (optional, will execute if omitted)")
    args = parser.parse_args()

    passed, mismatches = compare(args.case, args.actual)
    case_name = Path(args.case).name
    if passed:
        print(f"PASS: {case_name}")
        print("  - Total groups, assignments, and invariants all satisfied.")
        sys.exit(0)
    else:
        print(f"FAIL: {case_name}")
        for m in mismatches:
            print(f"  [X] {m}")
        sys.exit(1)


if __name__ == "__main__":
    main()
