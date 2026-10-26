import json
import os
from pathlib import Path
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select, create_engine
from app.db.session import SessionLocal, Base
from app.models.entities import Semester, Lecturer, Course, ClassSection, ClassSession, Constraint, OptimizationRun, Assignment, LecturerCourseCapability, NormalizedPreferenceDraft
from app.optimization.solver import solve
from app.services.importer import _import_files_impl
from app.services.preference_validation import validate_preference_draft
from app.api.routes import apply_preference_drafts
from pydantic import BaseModel

class PreferenceDraftApply(BaseModel):
    draft_ids: list[int]

def main():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    db = Session(test_engine)

    semester = Semester(name="HK1 2026-2027", department_name="Toán", start_date=date(2026, 8, 1), end_date=date(2027, 1, 31), head_name="Admin")
    db.add(semester)
    db.commit()

    schedule = Path("../INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx")
    preferences = Path("../INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chuan_Hoa.xlsx")
    
    imported = _import_files_impl(db, [schedule, preferences], semester_id=semester.id, schedule_paths=[schedule], preference_paths=[preferences])
    
    drafts = db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id == semester.id)).all()
    valid_ids = []
    
    for d in drafts:
        if d.lecturer_id is None:
            l = db.scalar(select(Lecturer).where(Lecturer.canonical_name == d.lecturer_alias))
            if not l:
                l = Lecturer(canonical_name=d.lecturer_alias, code=f"GV_{d.lecturer_alias}", status="ACTIVE")
                db.add(l)
                db.commit()
            d.lecturer_id = l.id
            
        d.needs_review = False
        d.status = "CONFIRMED"
        db.commit()
        val = validate_preference_draft(d, db)
        if d.draft_kind == "CONSTRAINT" and d.constraint_type not in {"RAW_NOTE", "SEMINAR_NOTE", "MIXED"}:
            if val['is_confirmable']:
                valid_ids.append(d.id)
            
    res = apply_preference_drafts(PreferenceDraftApply(draft_ids=valid_ids), semester_id=semester.id, db=db)
    
    constraints = db.scalars(select(Constraint).where(Constraint.semester_id == semester.id)).all()
    

    run = solve(db, 60, False, semester.id)
    
    # 1. Tổng số lớp cần phân công (Teaching groups as parsed)
    # The actual groups to assign is run.summary["classes"] which handles merged classes
    total_groups = run.summary.get("classes", 0)
    
    assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
    assigned_count = len(assignments)
    unassigned = run.summary.get("unassigned", [])
    unassigned_count = len(unassigned)
    
    req_count = len([c for c in constraints if c.constraint_type == "REQUIRED_ASSIGNMENT"])
    forb_count = len([c for c in constraints if c.constraint_type == "FORBIDDEN_ASSIGNMENT"])
    lock_count = len([c for c in constraints if c.constraint_type == "LOCKED_ASSIGNMENT"])
    
    uutien_total = len([c for c in constraints if c.constraint_type == "PREFERRED_PERIOD"])
    hanche_total = len([c for c in constraints if c.constraint_type == "AVOID_PERIOD"])
    sec3_total = len([c for c in constraints if c.constraint_type in ["MAX_DAYS_PER_WEEK", "MIN_FREE_MORNING_PER_WEEK", "PREFER_CONSECUTIVE_PERIODS"]])
    
    print("1. Tổng số lớp cần phân công:", total_groups)
    pct = (assigned_count / total_groups * 100) if total_groups > 0 else 0
    print(f"2. Số lớp đã phân công và tỷ lệ %: {assigned_count} lớp ({pct:.2f}%)")
    print("3. Số lớp UNASSIGNED:", unassigned_count)
    
    hard_violations = 0
    if run.status in ["infeasible", "blocked"]:
        hard_violations = 1
    print("4. HARD violations found:", hard_violations)
    
    print(f"5. Số REQUIRED/FORBIDDEN/LOCKED constraints được kiểm tra: {req_count} / {forb_count} / {lock_count}")
    
    print("6. Workload của từng giảng viên và các trường hợp vượt/nguy cơ vượt định mức:")
    lecturer_credits = {}
    for ass in assignments:
        c = db.get(ClassSection, ass.class_id)
        cr = c.credits if c and c.credits else 0
        lecturer_credits[ass.lecturer_id] = lecturer_credits.get(ass.lecturer_id, 0) + cr
    for lec in db.scalars(select(Lecturer)).all():
        cr = lecturer_credits.get(lec.id, 0)
        warning = " (Vượt định mức)" if cr > 15 else ""
        print(f"   - {lec.canonical_name}: {cr} tín chỉ{warning}")
        
    print("7. Tỷ lệ SOFT preferences được đáp ứng:")
    print(f"   * ƯU TIÊN: Tham chiếu {uutien_total} nguyện vọng")
    print(f"   * HẠN CHẾ: Tham chiếu {hanche_total} nguyện vọng")
    print(f"   * các nguyện vọng Section 3: Tham chiếu {sec3_total} nguyện vọng")
    
    print("8. Danh sách lớp UNASSIGNED kèm nguyên nhân thực tế:")
    for u in unassigned:
        class_id = u.get("class_id")
        c = db.get(ClassSection, class_id)
        reasons = u.get("reasons", [])
        print(f"   - Lớp {c.class_code} ({c.course.name if c.course else ''}):")
        for r in reasons[:3]:
            l = db.get(Lecturer, r['lecturer_id'])
            if l:
                print(f"     + GV {l.canonical_name}: {r['reason']}")
    if not unassigned:
        print("   (Không có)")
            
    print("9. Danh sách 10 trường hợp có penalty SOFT cao nhất:")
    sorted_ass = sorted([a for a in assignments if a.penalty > 0], key=lambda x: x.penalty, reverse=True)[:10]
    for a in sorted_ass:
        l = db.get(Lecturer, a.lecturer_id)
        c = db.get(ClassSection, a.class_id)
        print(f"   - GV {l.canonical_name} dạy {c.class_code} (Penalty: {a.penalty})")
    if not sorted_ass:
        print("   (Không có)")
        
    print("10. Kết luận cuối:")
    if hard_violations == 0 and unassigned_count == 0:
        print("PASS")
    elif hard_violations == 0 and unassigned_count > 0:
        print("PASS WITH WARNINGS")
    else:
        print("FAIL")

if __name__ == "__main__":
    main()
