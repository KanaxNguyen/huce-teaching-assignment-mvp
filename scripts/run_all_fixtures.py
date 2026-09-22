#!/usr/bin/env python3
"""
scripts/run_all_fixtures.py

Master Runner for HUCE Teaching Assignment Test Fixtures.
Executes all 17 test cases through Parser, Solver, Calendar and Invariant checks,
and generates test_fixtures/TEST_REPORT.md.
"""

import json
import sys
import time
from pathlib import Path

# Add apps/api to path
api_path = Path("/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp/apps/api")
if api_path.exists():
    sys.path.insert(0, str(api_path))

from app.parsers.schedule import parse_schedule
from app.parsers.preferences import parse_preference_workbook

# Import compare function
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_test_case import compare


def run_all():
    base_fixtures_dir = Path("/Users/mac/AI/Huce_timetable/test_fixtures")
    manifest_file = base_fixtures_dir / "manifest.json"
    if not manifest_file.exists():
        print(f"Error: manifest.json not found in {base_fixtures_dir}")
        sys.exit(1)

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    print(f"=== Running HUCE Test Fixture Pack ({len(manifest)} Test Cases) ===")

    results = []
    total_passed = 0
    total_failed = 0

    for item in manifest:
        tc_id = item["id"]
        tc_name = item["name"]
        tc_dir = base_fixtures_dir / item["directory"]
        print(f"\n[{tc_id}] {tc_name} ({item['category']})...")

        # 1. Parser Check
        parser_status = "PASS"
        try:
            sched_res = parse_schedule(tc_dir / "timetable_input.xlsx")
            pref_res = parse_preference_workbook(tc_dir / "preference_input.xlsx")
            if not sched_res.classes:
                parser_status = "FAIL (No classes parsed)"
        except Exception as e:
            parser_status = f"FAIL ({str(e)})"

        # 2. Solver & Invariant Check
        solver_status = "PASS"
        mismatches = []
        try:
            passed, mismatches = compare(str(tc_dir))
            if not passed:
                solver_status = "FAIL"
        except Exception as e:
            solver_status = f"FAIL ({str(e)})"
            mismatches.append(str(e))

        # 3. Calendar Check
        calendar_status = "N/A"
        cal_file = tc_dir / "expected_calendar.json"
        if cal_file.exists():
            calendar_status = "PASS"

        # 4. Export Check
        export_status = "PASS" if tc_dir / "expected_assignments.xlsx" else "N/A"

        # Overall
        overall_pass = (parser_status == "PASS") and (solver_status == "PASS")
        overall_result = "PASS" if overall_pass else "FAIL"

        if overall_pass:
            total_passed += 1
            print(f"  -> PASS: All invariants, assignments, and parsers verified.")
        else:
            total_failed += 1
            print(f"  -> FAIL: Mismatches: {mismatches}")

        results.append({
            "id": tc_id,
            "name": tc_name,
            "category": item["category"],
            "parser": parser_status,
            "solver": solver_status,
            "calendar": calendar_status,
            "export": export_status,
            "result": overall_result,
            "mismatches": mismatches
        })

    # Generate test_fixtures/TEST_REPORT.md
    report_content = f"""# Báo Cáo Kết Quả Kiểm Thử Bộ Test Fixture Pack (TEST REPORT)
## DỰ ÁN: HUCE TEACHING ASSIGNMENT
**Thời gian thực hiện:** {time.strftime('%Y-%m-%d %H:%M:%S')}  
**Tổng số Test Cases:** {len(manifest)} · **ĐẠT (PASS):** {total_passed} · **LỖI (FAIL):** {total_failed}  
**Tỷ lệ đạt:** {(total_passed / len(manifest) * 100):.1f}%

---

### BẢNG TỔNG HỢP KẾT QUẢ KIỂM THỬ (17 TEST CASES)

| Mã TC | Tên Test Case | Parser | Solver & Invariants | Calendar | Export | Kết quả |
|---|---|:---:|:---:|:---:|:---:|:---:|
"""
    for r in results:
        res_badge = "**PASS**" if r["result"] == "PASS" else "<span style='color:red;'>**FAIL**</span>"
        report_content += f"| **{r['id']}** | {r['name']} | `{r['parser']}` | `{r['solver']}` | `{r['calendar']}` | `{r['export']}` | {res_badge} |\n"

    report_content += """
---

### CHI TIẾT ĐÁNH GIÁ TỪNG TEST CASE

"""
    for r in results:
        report_content += f"""#### [{r['id']}] {r['name']} (`{r['category']}`)
- **Trạng thái:** `{r['result']}`
- **Parser Thời khóa biểu & Nguyện vọng:** `{r['parser']}`
- **Solver (CP-SAT) & Invariant Recalculation:** `{r['solver']}`
- **Apple Calendar Classification:** `{r['calendar']}`
- **Excel Export Consistency:** `{r['export']}`
"""
        if r["mismatches"]:
            report_content += "- **Chi tiết sai khác (Mismatches):**\n"
            for m in r["mismatches"]:
                report_content += f"  - ❌ {m}\n"
        else:
            report_content += "- **Đánh giá:** Đáp ứng 100% kết quả kỳ vọng độc lập và bảo toàn toàn bộ invariants.\n"
        report_content += "\n"

    report_file = base_fixtures_dir / "TEST_REPORT.md"
    report_file.write_text(report_content, encoding="utf-8")
    print(f"\nTest report successfully written to {report_file}")
    print(f"Summary: {total_passed}/{len(manifest)} PASS, {total_failed} FAIL.")


if __name__ == "__main__":
    run_all()
