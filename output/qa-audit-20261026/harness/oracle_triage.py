"""Rebuild selected oracle cases (same RNG stream) and dump the instance and both answers."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import algo_audit as aa  # noqa: E402
import independent_checker as ic  # noqa: E402

wanted = {int(x) for x in sys.argv[2].split(",")}
rng = random.Random(20261026)
out = []
for index in range(max(wanted) + 1):
    sid = aa.random_instance(rng)
    if index not in wanted:
        continue
    con, sem, classes, sessions, caps, constraints, _ = ic.load(aa.DB_PATH, sid)
    expected = aa.oracle(sid)
    run_id, status, score, summary = aa.run_solver(sid)
    solver_plan = ic.check(aa.DB_PATH, sid, run_id)[1] if status in {"optimal", "feasible"} else {}
    out.append({
        "case": index,
        "classes": {cid: {k: c[k] for k in ("class_code", "course_id", "credits", "merged_group_id", "merged_confirmed", "locked_assignment", "assigned_lecturer_id")}
                    | {"meetings": [(s["weekday"], s["start_period"], s["end_period"], s["active_weeks"]) for s in sessions[cid]]} for cid, c in classes.items()},
        "caps": [(c["lecturer_id"], c["course_id"], c["allowed"], c["confirmed"]) for c in caps],
        "rules": [(c["lecturer_id"], c["constraint_type"], c["hardness"], c["weight"], c["target"]) for c in constraints],
        "oracle": expected, "solver": {"status": status, "score": score, "plan": solver_plan, "code": summary.get("code"),
                                        "reasons": summary.get("candidate_reasons")},
    })
print(json.dumps(out, default=str, ensure_ascii=False, indent=1))
