"""Timed experiments through the HTTP API (TestClient), fresh SQLite per scenario, 3 runs each.

Usage: PYTHONPATH=apps/api .venv/bin/python experiments.py <evidence_dir> <work_dir> <code_hash>
"""
import csv
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

OUT, WORK, CODE_HASH = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
OUT.mkdir(parents=True, exist_ok=True); WORK.mkdir(parents=True, exist_ok=True)
DB = WORK / "exp.db"
os.environ.update(ENVIRONMENT="development", UPLOAD_DIR=str(WORK / "up"), EXPORT_DIR=str(WORK / "ex"), DATABASE_URL=f"sqlite:///{DB}")
sys.path.insert(0, str(Path(__file__).parent))
import independent_checker as ic  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from app.db.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

P = "/api/v1"
ROOT = Path("/Users/mac/AI/Huce_timetable")
REAL_XLS = Path("/Users/mac/Downloads/phan-cong-giang-day-lich-hoc-to-bo-mon-03-08-2026.xls")
PAIR_SCHEDULE = ROOT / "INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx"
PAIR_PREF = ROOT / "INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chi_Tiet.xlsx"
HEADER = ("STT", "Mã học phần", "Tên môn học", "Mã lớp học", "Ghi chú", "Thứ", "Tiết", "Phòng học", "Số TC", "Số SV", "Bắt đầu", "Kết thúc", "Tuần", "Giảng viên")
ROWS = []


def fresh():
    engine.dispose()
    if DB.exists():
        DB.unlink()
    Base.metadata.create_all(engine)
    return TestClient(app)


def api(c, method, path, **kw):
    r = c.request(method, P + path, **kw)
    if r.status_code != 200:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:600]}")
    return r.json()


def semester(c, start, end, name):
    return api(c, "POST", "/semesters", json=dict(name=name, department_name="Toán học", head_name="QA", start_date=start, end_date=end))["id"]


def stage(c, sid, path, role="CURRENT_SCHEDULE"):
    s = api(c, "POST", f"/sources/upload?semester_id={sid}&source_type={role}", files={"file": (path.name, path.read_bytes())})
    p = api(c, "POST", f"/sources/{s['id']}/preview?semester_id={sid}", json={"source_type": role})
    return c.post(P + f"/sources/{s['id']}/activate?semester_id={sid}", json={"source_type": role, "confirmed": True, "preview_token": p["preview_token"]})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def run(c, sid, scenario, dataset_hash, n, limit=10, note=""):
    started = time.perf_counter()
    r = c.post(P + f"/optimization/run?semester_id={sid}", json={"time_limit_seconds": limit, "confirm_merged_suggestions": False})
    http_s = time.perf_counter() - started
    body = r.json()
    summary = body.get("summary") or {}
    exp = summary.get("experiment") or {}
    comps = exp.get("objective_components") or {}
    classes = api(c, "GET", f"/classes?semester_id={sid}")
    issues, assigned = ic.check(str(DB), sid, body["run_id"]) if body.get("status") in ("optimal", "feasible") else ([], {})
    ready = api(c, "GET", f"/readiness?semester_id={sid}")
    bound = exp.get("best_objective_bound")
    score = body.get("score")
    ROWS.append({
        "scenario": scenario, "run": n, "dataset_sha256_16": dataset_hash, "code_hash": CODE_HASH, "http_status": r.status_code,
        "status": body.get("status"), "time_limit_s": limit, "workers": (exp.get("configuration") or {}).get("num_search_workers"),
        "random_seed": (exp.get("configuration") or {}).get("random_seed"), "confirm_merged": (exp.get("configuration") or {}).get("confirm_merged"),
        "classes": len(classes), "meetings": sum(len(k["sessions"]) for k in classes), "lecturers_participating": summary.get("lecturer_count"),
        "assigned": len(assigned), "unassigned": len(classes) - len(assigned), "locked": sum(1 for k in classes if k["locked_assignment"]),
        "independent_hard_violations": len(issues), "objective": score, "best_bound": bound,
        "gap": (abs(score - bound) / max(1, abs(score))) if (score is not None and bound is not None) else None,
        "unassigned_component": comps.get("unassigned"), "zero_lecturer_component": comps.get("zero_assigned_lecturers"),
        "workload_disparity_component": comps.get("workload_disparity"), "soft_component": comps.get("soft_preferences"),
        "model_build_s": exp.get("model_build_seconds"), "solver_wall_s": exp.get("solver_wall_time_seconds"),
        "solver_pipeline_s": exp.get("solver_pipeline_seconds"), "http_pipeline_s": round(http_s, 4),
        "readiness_ready": ready.get("ready"), "summary_code": summary.get("code"), "note": note,
    })
    print(scenario, n, body.get("status"), len(assigned), "/", len(classes), "viol", len(issues), "obj", score, "t", round(http_s, 3), flush=True)
    return body, assigned


def gen_workbook(name, rows):
    wb = Workbook(); ws = wb.active; ws.title = "Schedule"; ws.append(HEADER)
    for i, r in enumerate(rows, 1):
        ws.append((str(i), *r))
    p = WORK / name; wb.save(p); return p


def give_caps(c, matrix):
    lecturers = {l["code"]: l["id"] for l in api(c, "GET", "/lecturers")}
    for code, name, course_ids in matrix:
        if code not in lecturers:
            lecturers[code] = api(c, "POST", "/lecturers", json={"code": code, "name": name})["id"]
        for cid in course_ids:
            api(c, "PUT", f"/lecturers/{lecturers[code]}/capabilities", json={"course_id": cid, "allowed": True, "confirmed": True})


def scenario_fixture(case):
    c = fresh(); d = ROOT / "test_fixtures" / case
    meta = json.loads((d / "fixture_meta.json").read_text())
    sid = semester(c, "2026-09-07", "2027-01-24", case)
    stage(c, sid, d / "timetable_input.xlsx"); stage(c, sid, d / "preference_input.xlsx", "PREFERENCE")
    courses = {k["course_code"]: k["course_id"] for k in api(c, "GET", f"/classes?semester_id={sid}")}
    give_caps(c, [(code, code, [courses[x] for x in cs if x in courses]) for code, cs in meta.get("capabilities", {}).items()])
    ids = []
    for dft in api(c, "GET", f"/preference-drafts?semester_id={sid}"):
        if dft.get("lecturer_id") and c.patch(P + f"/preference-drafts/{dft['id']}?semester_id={sid}", json={"status": "CONFIRMED"}).status_code == 200:
            ids.append(dft["id"])
    if ids:
        api(c, "POST", f"/preference-drafts/apply?semester_id={sid}", json={"draft_ids": ids})
    h = sha(d / "timetable_input.xlsx")
    for n in range(1, 4):
        run(c, sid, f"fixture-{case}", h, n)


def scenario_real_xls():
    c = fresh(); sid = semester(c, "2026-08-03", "2027-01-31", "real-03-08")
    a = stage(c, sid, REAL_XLS)
    h = sha(REAL_XLS)
    last = None
    for n in range(1, 4):
        last = run(c, sid, "real-03-08-open (no preferences)", h, n)
    # Controlled approved soft wish for every lecturer: avoid evening (13-15), weight 1.
    for l in api(c, "GET", "/lecturers"):
        d = api(c, "POST", f"/preference-drafts?semester_id={sid}", json=dict(lecturer_id=l["id"], context_type="TEACHING", constraint_type="AVOID_PERIOD",
                                                                            day_scope="ALL_DAYS", periods=[1, 2, 3], hardness="soft", weight=1, note="QA controlled", status="CONFIRMED"))
        api(c, "POST", f"/preference-drafts/apply?semester_id={sid}", json={"draft_ids": d["ids"]})
    for n in range(1, 4):
        last = run(c, sid, "real-03-08-controlled-soft (approved AVOID 1-3 all lecturers)", h, n)
    body, assigned = last
    locked = 0
    for cid in list(assigned)[:85]:
        if c.post(P + f"/classes/{cid}/lock?semester_id={sid}").status_code == 200:
            locked += 1
    for n in range(1, 4):
        run(c, sid, "real-03-08-lock-85", h, n, note=f"{locked} locks applied")
    # Everyone hard-busy all week.
    for l in api(c, "GET", "/lecturers"):
        api(c, "POST", f"/constraints?semester_id={sid}", json={"name": "busy", "constraint_type": "UNAVAILABLE", "hardness": "hard", "lecturer_id": l["id"],
                                                                "target": {"day_scope": "ALL_DAYS", "periods": list(range(1, 16))}})
    for cid in assigned:
        c.post(P + f"/classes/{cid}/unlock?semester_id={sid}")
    run(c, sid, "real-03-08-all-hard-busy", h, 1)


def scenario_real_pair():
    c = fresh(); sid = semester(c, "2026-08-03", "2027-01-31", "real-pair")
    a = stage(c, sid, PAIR_SCHEDULE)
    h = sha(PAIR_SCHEDULE) + "+" + sha(PAIR_PREF)
    act_note = f"schedule activate {a.status_code}"
    p = stage(c, sid, PAIR_PREF, "PREFERENCE")
    for n in range(1, 4):
        run(c, sid, "real-pair-open (drafts not approved)", h, n, note=act_note + f"; preference activate {p.status_code}")
    confirmed = api(c, "POST", f"/preference-drafts/confirm-high?semester_id={sid}")
    ids = [d["id"] for d in api(c, "GET", f"/preference-drafts?semester_id={sid}") if d.get("status") == "CONFIRMED" and d.get("is_confirmable")]
    applied = c.post(P + f"/preference-drafts/apply?semester_id={sid}", json={"draft_ids": ids}) if ids else None
    for n in range(1, 4):
        run(c, sid, "real-pair-high-confidence-confirmed+applied", h, n,
            note=f"confirm-high={confirmed}; applied={applied.status_code if applied else None} ids={len(ids)}")


def scenario_same_slot():
    c = fresh(); sid = semester(c, "2026-09-07", "2027-01-24", "same-slot")
    rows = [("399001", "Môn A", f"S{i}", None, "4", "4-6", f"R{i}", "3", "60", "07/09/2026", "24/01/2027", "123456789", None) for i in range(30)]
    p = gen_workbook("same-slot.xlsx", rows); stage(c, sid, p)
    cid = api(c, "GET", f"/classes?semester_id={sid}")[0]["course_id"]
    give_caps(c, [(f"G{i:02d}", f"GV {i}", [cid]) for i in range(10)])
    for n in range(1, 4):
        run(c, sid, "synthetic-30-classes-one-slot-10-lecturers (bound 20 unassigned)", sha(p), n)


def scenario_large():
    rng = random.Random(42)
    c = fresh(); sid = semester(c, "2026-09-07", "2027-01-24", "large")
    rows = []
    for i in range(600):
        course = f"39{rng.randint(1, 15):04d}"
        weeks = rng.choice(["123456789", "12345", "     67890", "1 3 5 7 9", "123456789012345"])
        rows.append((course, f"Môn {course}", f"L{i:03d}", None, str(rng.randint(2, 7)), rng.choice(["1-3", "4-6", "7-9", "10-12", "13-15"]),
                     f"R{i}", rng.choice(["2", "3", "4"]), "60", "07/09/2026", "24/01/2027", weeks, None))
    p = gen_workbook("large.xlsx", rows); stage(c, sid, p)
    courses = sorted({k["course_id"] for k in api(c, "GET", f"/classes?semester_id={sid}")})
    give_caps(c, [(f"B{i:02d}", f"GV {i}", [x for x in courses if rng.random() < 0.4]) for i in range(40)])
    for n in range(1, 4):
        run(c, sid, "synthetic-large-600-classes-40-lecturers", sha(p), n, limit=30)


if __name__ == "__main__":
    for case in ("TC01_basic_assignment", "TC15_full_mixed_mini_semester", "TC16_no_eligible_lecturer", "TC17_all_capable_hard_unavailable"):
        scenario_fixture(case)
    scenario_real_xls()
    scenario_real_pair()
    scenario_same_slot()
    scenario_large()
    with (OUT / "EXPERIMENT_RESULTS.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ROWS[0].keys())); w.writeheader(); w.writerows(ROWS)
    (OUT / "experiments.json").write_text(json.dumps(ROWS, ensure_ascii=False, indent=1, default=str))
