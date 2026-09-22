from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Course,
    Lecturer,
    LecturerCourseCapability,
    NormalizedPreferenceDraft,
    OptimizationRun,
    Semester,
)
from app.optimization.solver import _overlap, _slot_match
from app.optimization.occurrences import are_classes_mergeable
from app.services.lecturer_master import participation_reason
from app.services.source_authority import latest_current_run


def _format_schedule_summary(sessions: list[ClassSession]) -> str:
    if not sessions:
        return "Chưa có lịch"
    parts = []
    for s in sessions:
        weeks_str = f"Tuần {min(s.active_weeks)}-{max(s.active_weeks)}" if s.active_weeks else (s.raw_weeks or "")
        room_str = f" · {s.room}" if s.room else ""
        weeks_part = f" ({weeks_str}{room_str})" if weeks_str or room_str else ""
        parts.append(f"T{s.weekday} Tiết {s.start_period}–{s.end_period}{weeks_part}")
    return " ; ".join(parts)


def get_unassigned_classes_for_run(db: Session, semester_id: int, run_id: int | None = None) -> list[ClassSection]:
    run = None
    if run_id is not None:
        run = db.get(OptimizationRun, run_id)
        if run and run.semester_id != semester_id:
            run = None
    if not run and run_id is None:
        run = latest_current_run(db, semester_id)

    query = (
        select(ClassSection)
        .where(ClassSection.semester_id == semester_id)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
        .order_by(ClassSection.id)
    )
    all_classes = db.scalars(query).all()

    if run and run.status in {"optimal", "feasible"}:
        assigned_ids = set(
            db.scalars(select(Assignment.class_id).where(Assignment.run_id == run.id)).all()
        )
        return [item for item in all_classes if item.id not in assigned_ids]
    return [item for item in all_classes if item.assigned_lecturer_id is None]


def diagnose_unassigned_classes(
    db: Session, semester_id: int, run_id: int | None = None
) -> list[dict[str, Any]]:
    unassigned_classes = get_unassigned_classes_for_run(db, semester_id, run_id)
    if not unassigned_classes:
        return []

    semester = db.get(Semester, semester_id)
    run = db.get(OptimizationRun, run_id) if run_id else latest_current_run(db, semester_id)

    dept_id = semester.department_id if semester else None
    lec_query = select(Lecturer).order_by(Lecturer.id)
    if dept_id is not None:
        lec_query = lec_query.where(
            or_(
                Lecturer.department_id == dept_id,
                Lecturer.department_id.is_(None),
            )
        )
    all_lecturers = db.scalars(lec_query).all()
    active_lecturers = [
        lec for lec in all_lecturers if participation_reason(db, lec, semester_id) is None
    ]
    active_lecturer_ids = {lec.id for lec in active_lecturers}
    lecturers_by_id = {lec.id: lec for lec in all_lecturers}

    # Load all confirmed capabilities scoped to department
    cap_query = select(LecturerCourseCapability).where(
        LecturerCourseCapability.allowed.is_(True),
        LecturerCourseCapability.confirmed.is_(True),
        or_(
            LecturerCourseCapability.source.is_(None),
            LecturerCourseCapability.source != "HYPOTHETICAL_ALL",
        ),
    )
    if dept_id is not None:
        cap_query = cap_query.where(
            or_(
                LecturerCourseCapability.department_id == dept_id,
                LecturerCourseCapability.department_id.is_(None),
            )
        )
    capabilities = defaultdict(list)
    for cap in db.scalars(cap_query).all():
        if cap.lecturer_id in active_lecturer_ids:
            capabilities[cap.course_id].append(cap.lecturer_id)

    # Course equivalence bridging for unassigned diagnostics
    from app.services.capability_resolution import _plain_text
    all_courses = {c.id: c for c in db.scalars(select(Course)).all()}
    courses_by_norm = defaultdict(list)
    for c in all_courses.values():
        if c.name:
            cnorm = _plain_text(c.name)
            if cnorm and len(cnorm) >= 3:
                courses_by_norm[cnorm].append(c)

    for cnorm, eq_courses in courses_by_norm.items():
        if len(eq_courses) < 2:
            continue
        for src_c in eq_courses:
            for lec_id in list(capabilities.get(src_c.id, [])):
                for dst_c in eq_courses:
                    if dst_c.id != src_c.id and lec_id not in capabilities[dst_c.id]:
                        capabilities[dst_c.id].append(lec_id)

    # Load active confirmed constraints
    constraints = db.scalars(
        select(Constraint).where(
            Constraint.semester_id == semester_id,
            Constraint.active.is_(True),
            Constraint.confirmed.is_(True),
        )
    ).all()
    lecturer_constraints = defaultdict(list)
    for c in constraints:
        if c.lecturer_id:
            lecturer_constraints[c.lecturer_id].append(c)

    # Map current assignments in this run or database
    assigned_classes_by_lecturer = defaultdict(list)
    all_assigned_classes = []
    if run and run.status in {"optimal", "feasible"}:
        assignments = db.scalars(
            select(Assignment)
            .where(Assignment.run_id == run.id)
            .options(
                selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
                selectinload(Assignment.class_section).selectinload(ClassSection.course),
            )
        ).all()
        for ass in assignments:
            if ass.class_section:
                assigned_classes_by_lecturer[ass.lecturer_id].append(ass.class_section)
                all_assigned_classes.append(ass.class_section)
    else:
        sections = db.scalars(
            select(ClassSection)
            .where(ClassSection.semester_id == semester_id, ClassSection.assigned_lecturer_id.is_not(None))
            .options(
                selectinload(ClassSection.sessions),
                selectinload(ClassSection.course),
            )
        ).all()
        for s in sections:
            assigned_classes_by_lecturer[s.assigned_lecturer_id].append(s)
            all_assigned_classes.append(s)

    results = []
    for section in unassigned_classes:
        capable_lec_ids = set(capabilities.get(section.course_id, []))
        schedule_text = _format_schedule_summary(section.sessions)

        # Lecturer breakdown for this section
        reasons_per_lecturer: dict[int, str] = {}
        hard_unavailable_lecs: set[int] = set()
        colliding_lecs: set[int] = set()
        workload_lecs: set[int] = set()
        eligible_lecs: set[int] = set()

        for lec_id in active_lecturer_ids:
            if lec_id not in capable_lec_ids:
                reasons_per_lecturer[lec_id] = "NO_CAPABILITY"
                continue

            # Check hard availability
            has_hard_unavail = False
            for c in lecturer_constraints.get(lec_id, []):
                kind = c.constraint_type.upper()
                if c.hardness == "hard" and kind in {"UNAVAILABLE", "BUSY_EVENT", "AVOID_PERIOD", "AVOID_DAYS"}:
                    if any(_slot_match(session, c.target or {}, semester) for session in section.sessions):
                        has_hard_unavail = True
                        break
            if has_hard_unavail:
                hard_unavailable_lecs.add(lec_id)
                reasons_per_lecturer[lec_id] = "HARD_AVAILABILITY_CONFLICT"
                continue

            # Check timetable collision
            collisions = []
            for other in assigned_classes_by_lecturer.get(lec_id, []):
                if other.id == section.id:
                    continue
                if section.merged_group_id and section.merged_group_id == other.merged_group_id:
                    continue
                for s1 in section.sessions:
                    for s2 in other.sessions:
                        if _overlap(s1, s2):
                            overlap_w = sorted(set(s1.active_weeks or []).intersection(s2.active_weeks or []))
                            collisions.append((other.class_code, overlap_w))
            if collisions:
                colliding_lecs.add(lec_id)
                reasons_per_lecturer[lec_id] = "TIMETABLE_COLLISION"
                continue

            # Check workload limit
            assigned_count = len(assigned_classes_by_lecturer.get(lec_id, []))
            has_workload_limit = False
            for c in lecturer_constraints.get(lec_id, []):
                if c.hardness == "hard" and c.constraint_type.upper() == "MAX_CLASSES":
                    max_classes = (c.target or {}).get("max", float("inf"))
                    if assigned_count + 1 > max_classes:
                        has_workload_limit = True
                        break
            if has_workload_limit:
                workload_lecs.add(lec_id)
                reasons_per_lecturer[lec_id] = "WORKLOAD_HARD_LIMIT"
                continue

            eligible_lecs.add(lec_id)
            reasons_per_lecturer[lec_id] = "ELIGIBLE"

        # Determine Root Cause and analyze simultaneous classes
        root_cause = "UNKNOWN"
        root_cause_label = "Chưa xác định"
        root_cause_severity = "warning"
        bottleneck_details = None

        simultaneous_classes = []
        all_semester_classes = all_assigned_classes + unassigned_classes
        for s1 in section.sessions:
            for other in all_semester_classes:
                if other.id == section.id or any(o.id == other.id for o in simultaneous_classes):
                    continue
                if any(_overlap(s1, s2) for s2 in other.sessions):
                    simultaneous_classes.append(other)

        total_simultaneous = len(simultaneous_classes) + 1
        avail_cap_lecs = capable_lec_ids - hard_unavailable_lecs

        same_course_sim = [
            c for c in simultaneous_classes
            if are_classes_mergeable(section, c)
        ]

        free_lecs = [
            lec.canonical_name for lec in active_lecturers
            if lec.id not in colliding_lecs and lec.id not in hard_unavailable_lecs and lec.id not in capable_lec_ids
        ]

        if not capable_lec_ids:
            root_cause = "NO_CAPABILITY"
            root_cause_label = "Thiếu năng lực giảng dạy (0 GV có năng lực)"
            root_cause_severity = "critical"
        elif capable_lec_ids.issubset(hard_unavailable_lecs):
            root_cause = "HARD_AVAILABILITY_CONFLICT"
            root_cause_label = "Toàn bộ GV có năng lực đều bận cứng"
            root_cause_severity = "critical"
        elif eligible_lecs:
            root_cause = "ELIGIBLE_CANDIDATE_AVAILABLE"
            root_cause_label = f"Có {len(eligible_lecs)} ứng viên khả thi (Có thể gán thủ công)"
            root_cause_severity = "info"
        else:
            if total_simultaneous > len(avail_cap_lecs) or (len(same_course_sim) + 1 > len(avail_cap_lecs)):
                root_cause = "GLOBAL_INFEASIBILITY"
                root_cause_label = f"Nghẽn tài nguyên khung giờ ({total_simultaneous} lớp cùng giờ / {len(avail_cap_lecs)} GV khả dụng)"
                root_cause_severity = "warning"
                first_session = section.sessions[0] if section.sessions else None
                if first_session:
                    bottleneck_details = {
                        "weekday": first_session.weekday,
                        "period_range": f"{first_session.start_period}–{first_session.end_period}",
                        "overlapping_classes_count": total_simultaneous,
                        "available_lecturers_count": len(avail_cap_lecs),
                        "shortage": max(1, total_simultaneous - len(avail_cap_lecs)),
                    }
            elif colliding_lecs:
                root_cause = "TIMETABLE_COLLISION"
                root_cause_label = "Trùng lịch với lớp khác đã phân công"
                root_cause_severity = "warning"
            elif workload_lecs:
                root_cause = "WORKLOAD_HARD_LIMIT"
                root_cause_label = "Vượt định mức tải giảng dạy tối đa"
                root_cause_severity = "warning"
            else:
                root_cause = "NO_ELIGIBLE_LECTURER"
                root_cause_label = "Không có giảng viên phù hợp"
                root_cause_severity = "warning"

        # Recommended actions
        actions = []
        same_course_codes = [c.class_code for c in same_course_sim]

        if root_cause == "NO_CAPABILITY":
            actions.append({
                "type": "REVIEW_CAPABILITY",
                "label": "Bổ sung năng lực môn",
                "description": f"Cập nhật năng lực giảng dạy môn {section.course.name} cho giảng viên phù hợp.",
            })
            if free_lecs:
                actions.append({
                    "type": "DEPARTMENT_POOL",
                    "label": "Huy động GV bộ môn",
                    "description": f"Các GV đang rảnh ca này có thể bổ sung năng lực: {', '.join(free_lecs[:3])}.",
                })
        elif root_cause == "HARD_AVAILABILITY_CONFLICT":
            actions.append({
                "type": "REVIEW_PREFERENCES",
                "label": "Xem nguyện vọng & nới lỏng",
                "description": "Xem lại nguyện vọng bận cứng của các giảng viên có năng lực và điều chỉnh nếu cần.",
            })
            if hard_unavailable_lecs:
                blocked_names = [lecturers_by_id[lid].canonical_name for lid in hard_unavailable_lecs if lid in lecturers_by_id]
                if blocked_names:
                    actions.append({
                        "type": "RELAX_PREFERENCES",
                        "label": "Nới lỏng bận cứng GV",
                        "description": f"Nới lỏng nguyện vọng bận của GV có năng lực: {', '.join(blocked_names[:3])} vào khung giờ này.",
                    })
            if same_course_codes:
                actions.append({
                    "type": "MERGE_CLASSES",
                    "label": "Gợi ý ghép lớp cùng ca",
                    "description": f"Ghép lớp {section.class_code} với các lớp cùng môn: {', '.join(same_course_codes[:3])} để tiết kiệm tài nguyên GV.",
                    "target_class_id": section.id,
                    "target_class_code": section.class_code,
                    "candidate_class_ids": [c.id for c in same_course_sim],
                    "candidate_class_codes": same_course_codes,
                })
            actions.append({
                "type": "REVIEW_CAPABILITY",
                "label": "Bổ sung GV năng lực khác",
                "description": "Bổ sung thêm giảng viên khác dạy được môn này.",
            })
            if free_lecs:
                actions.append({
                    "type": "DEPARTMENT_POOL",
                    "label": "Huy động GV bộ môn",
                    "description": f"Các GV đang rảnh ca này có thể bổ sung năng lực: {', '.join(free_lecs[:3])}.",
                })
        elif root_cause in {"TIMETABLE_COLLISION", "GLOBAL_INFEASIBILITY"}:
            actions.append({
                "type": "OPEN_CALENDAR",
                "label": "Xem trên lịch",
                "description": "Kiểm tra khung giờ trên Apple Calendar để phát hiện lớp có thể hoán đổi ca/lịch.",
            })
            if same_course_codes:
                actions.append({
                    "type": "MERGE_CLASSES",
                    "label": "Gợi ý ghép lớp cùng ca",
                    "description": f"Ghép lớp {section.class_code} với các lớp cùng môn: {', '.join(same_course_codes[:3])} để tiết kiệm tài nguyên GV.",
                    "target_class_id": section.id,
                    "target_class_code": section.class_code,
                    "candidate_class_ids": [c.id for c in same_course_sim],
                    "candidate_class_codes": same_course_codes,
                })
            if hard_unavailable_lecs:
                blocked_names = [lecturers_by_id[lid].canonical_name for lid in hard_unavailable_lecs if lid in lecturers_by_id]
                if blocked_names:
                    actions.append({
                        "type": "RELAX_PREFERENCES",
                        "label": "Nới lỏng bận cứng GV",
                        "description": f"Nới lỏng nguyện vọng bận của GV có năng lực: {', '.join(blocked_names[:3])} vào khung giờ này.",
                    })
            actions.append({
                "type": "REVIEW_CAPABILITY",
                "label": "Mở rộng phân công",
                "description": "Bổ sung thêm giảng viên có năng lực để giải tỏa điểm nghẽn.",
            })
            if free_lecs:
                actions.append({
                    "type": "DEPARTMENT_POOL",
                    "label": "Huy động GV bộ môn",
                    "description": f"Các GV đang rảnh ca này có thể bổ sung năng lực: {', '.join(free_lecs[:3])}.",
                })
        if eligible_lecs:
            actions.append({
                "type": "MANUAL_ASSIGN",
                "label": "Phân công thủ công",
                "description": f"Chủ động gán cho một trong {len(eligible_lecs)} giảng viên đủ điều kiện.",
            })

        results.append({
            "class_id": section.id,
            "course_id": section.course_id,
            "course_code": section.course.code,
            "course_name": section.course.name,
            "class_code": section.class_code,
            "credits": section.credits,
            "schedule_summary": schedule_text,
            "sessions": [
                {
                    "weekday": s.weekday,
                    "start_period": s.start_period,
                    "end_period": s.end_period,
                    "room": s.room,
                    "active_weeks": s.active_weeks or [],
                    "raw_weeks": s.raw_weeks,
                }
                for s in section.sessions
            ],
            "root_cause": root_cause,
            "root_cause_label": root_cause_label,
            "root_cause_severity": root_cause_severity,
            "eligible_candidates_count": len(eligible_lecs),
            "total_candidates_count": len(active_lecturers),
            "resolution_status": getattr(section, "resolution_status", "NEW") or "NEW",
            "resolution_notes": getattr(section, "resolution_notes", None),
            "recommended_actions": actions,
            "bottleneck_details": bottleneck_details,
        })

    # Sort by priority:
    # 1. ELIGIBLE_CANDIDATE_AVAILABLE (easy manual fix)
    # 2. NO_CAPABILITY (missing data)
    # 3. HARD_AVAILABILITY_CONFLICT
    # 4. GLOBAL_INFEASIBILITY
    # 5. TIMETABLE_COLLISION
    # 6. others
    priority_order = {
        "ELIGIBLE_CANDIDATE_AVAILABLE": 1,
        "NO_CAPABILITY": 2,
        "HARD_AVAILABILITY_CONFLICT": 3,
        "GLOBAL_INFEASIBILITY": 4,
        "TIMETABLE_COLLISION": 5,
        "WORKLOAD_HARD_LIMIT": 6,
        "LOCKED_CONFLICT": 7,
        "NO_ELIGIBLE_LECTURER": 8,
        "UNKNOWN": 9,
    }
    results.sort(key=lambda item: (priority_order.get(item["root_cause"], 99), item["class_code"]))
    return results


class CandidateAnalysisResult(list):
    def __init__(self, rows, course=None, eligible=None, excluded=None):
        super().__init__(rows)
        self.course = course
        self.eligible = eligible or []
        self.excluded = excluded or []
        self.analysis_rows = rows

    def __getitem__(self, key):
        if isinstance(key, str):
            if key == "course":
                return self.course
            if key == "eligible":
                return self.eligible
            if key == "excluded":
                return self.excluded
            if key == "analysis_rows":
                return self.analysis_rows
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, TypeError):
            return default

    def __contains__(self, item):
        if isinstance(item, str):
            return item in {"course", "eligible", "excluded", "analysis_rows"}
        return super().__contains__(item)

    def keys(self):
        return ["course", "eligible", "excluded", "analysis_rows"]

    def to_dict(self):
        return {
            "course": self.course,
            "eligible": self.eligible,
            "excluded": self.excluded,
            "analysis_rows": self.analysis_rows,
        }


def get_candidate_analysis(
    db: Session, semester_id: int, class_id: int, run_id: int | None = None
) -> CandidateAnalysisResult:
    section = db.scalar(
        select(ClassSection)
        .where(ClassSection.id == class_id, ClassSection.semester_id == semester_id)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
    )
    if not section:
        return CandidateAnalysisResult([])

    semester = db.get(Semester, semester_id)
    run = db.get(OptimizationRun, run_id) if run_id else latest_current_run(db, semester_id)

    dept_id = semester.department_id if semester else None
    lec_query = select(Lecturer).order_by(Lecturer.id)
    if dept_id is not None:
        lec_query = lec_query.where(
            or_(
                Lecturer.department_id == dept_id,
                Lecturer.department_id.is_(None),
            )
        )
    all_lecturers = db.scalars(lec_query).all()

    from app.models.entities import DepartmentProfile
    policy = None
    if dept_id:
        policy = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == dept_id))

    target_course = section.course or db.get(Course, section.course_id)
    equiv_course_ids = [section.course_id]
    equiv_map = {section.course_id: target_course}
    if target_course and target_course.name:
        from app.services.capability_resolution import _plain_text
        norm_name = _plain_text(target_course.name)
        if norm_name and len(norm_name) >= 3:
            for c in db.scalars(select(Course).where(Course.id != section.course_id)).all():
                if _plain_text(c.name) == norm_name:
                    equiv_course_ids.append(c.id)
                    equiv_map[c.id] = c

    # Load capabilities for this course and equivalent courses scoped to department
    caps_query = select(LecturerCourseCapability).where(
        LecturerCourseCapability.course_id.in_(equiv_course_ids),
        or_(
            LecturerCourseCapability.source.is_(None),
            LecturerCourseCapability.source != "HYPOTHETICAL_ALL",
        ),
    )
    if dept_id is not None:
        caps_query = caps_query.where(
            or_(
                LecturerCourseCapability.department_id == dept_id,
                LecturerCourseCapability.department_id.is_(None),
            )
        )
    capabilities_for_course = db.scalars(caps_query).all()
    caps_by_lecturer = {}
    cap_equiv_info = {}
    for c in capabilities_for_course:
        if c.course_id == section.course_id:
            caps_by_lecturer[c.lecturer_id] = c
    for c in capabilities_for_course:
        if c.course_id != section.course_id and c.lecturer_id not in caps_by_lecturer:
            caps_by_lecturer[c.lecturer_id] = c
            cap_equiv_info[c.lecturer_id] = equiv_map.get(c.course_id)

    # Load constraints
    constraints = db.scalars(
        select(Constraint).where(
            Constraint.semester_id == semester_id,
            Constraint.active.is_(True),
            Constraint.confirmed.is_(True),
        )
    ).all()
    lecturer_constraints = defaultdict(list)
    for c in constraints:
        if c.lecturer_id:
            lecturer_constraints[c.lecturer_id].append(c)

    # Load preference drafts to provide source sheet/cell provenance
    drafts = db.scalars(
        select(NormalizedPreferenceDraft).where(
            NormalizedPreferenceDraft.semester_id == semester_id,
            NormalizedPreferenceDraft.status != "REJECTED",
        )
    ).all()
    drafts_by_lecturer = defaultdict(list)
    for d in drafts:
        if d.lecturer_id:
            drafts_by_lecturer[d.lecturer_id].append(d)

    # Load assignments in run or db
    assigned_classes = defaultdict(list)
    if run and run.status in {"optimal", "feasible"}:
        assignments = db.scalars(
            select(Assignment)
            .where(Assignment.run_id == run.id)
            .options(
                selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
                selectinload(Assignment.class_section).selectinload(ClassSection.course),
            )
        ).all()
        for ass in assignments:
            if ass.class_section:
                assigned_classes[ass.lecturer_id].append(ass.class_section)
    else:
        sections = db.scalars(
            select(ClassSection)
            .where(ClassSection.semester_id == semester_id, ClassSection.assigned_lecturer_id.is_not(None))
            .options(
                selectinload(ClassSection.sessions),
                selectinload(ClassSection.course),
            )
        ).all()
        for s in sections:
            assigned_classes[s.assigned_lecturer_id].append(s)

    analysis_rows = []
    for lec in all_lecturers:
        inactive_reason = participation_reason(db, lec, semester_id)
        current_assigned = assigned_classes.get(lec.id, [])
        teaching_groups_count = len(current_assigned)
        credits_count = sum(item.credits for item in current_assigned)

        cap = caps_by_lecturer.get(lec.id)
        has_cap = False
        cap_forbidden = False
        cap_not_confirmed = False

        if cap is None:
            has_cap = False
        elif not cap.allowed:
            cap_forbidden = True
        elif not cap.confirmed:
            if policy and policy.allow_provisional_capability:
                has_cap = True
            else:
                cap_not_confirmed = True
        else:
            has_cap = True

        # Check hard unavailability
        hard_unavailable = False
        pref_source = None
        unavail_details = ""
        for c in lecturer_constraints.get(lec.id, []):
            kind = c.constraint_type.upper()
            if c.hardness == "hard" and kind in {"UNAVAILABLE", "BUSY_EVENT", "AVOID_PERIOD", "AVOID_DAYS"}:
                matched = any(_slot_match(s, c.target or {}, semester) for s in section.sessions)
                if matched:
                    hard_unavailable = True
                    # Look up draft for provenance
                    for d in drafts_by_lecturer.get(lec.id, []):
                        if d.source_sheet and d.source_cell:
                            pref_source = {
                                "sheet": d.source_sheet,
                                "cell": d.source_cell,
                                "raw_text": d.raw_text or "",
                            }
                            break
                    unavail_details = f"Bận cứng ({c.name or kind})"
                    if pref_source:
                        unavail_details += f" theo ghi chú tại {pref_source['sheet']}!{pref_source['cell']}"
                    break

        # Check timetable collisions
        has_collision = False
        collision_items = []
        for other in current_assigned:
            if other.id == section.id:
                continue
            if section.merged_group_id and section.merged_group_id == other.merged_group_id:
                continue
            for s1 in section.sessions:
                for s2 in other.sessions:
                    if _overlap(s1, s2):
                        overlap_w = sorted(set(s1.active_weeks or []).intersection(s2.active_weeks or []))
                        collision_items.append({
                            "class_id": other.id,
                            "class_code": other.class_code,
                            "course_name": other.course.name if other.course else "",
                            "weekday": s2.weekday,
                            "periods": f"{s2.start_period}–{s2.end_period}",
                            "overlapping_weeks": overlap_w,
                        })
        if collision_items:
            has_collision = True

        # Check workload limits
        workload_exceeded = False
        workload_details = ""
        for c in lecturer_constraints.get(lec.id, []):
            if c.hardness == "hard" and c.constraint_type.upper() == "MAX_CLASSES":
                limit = (c.target or {}).get("max", float("inf"))
                if teaching_groups_count + 1 > limit:
                    workload_exceeded = True
                    workload_details = f"Vượt quá số lớp tối đa cho phép ({limit} lớp)"
                    break

        # Check locked conflict
        is_locked_to_this = section.assigned_lecturer_id == lec.id and section.locked_assignment

        # Classify status
        if inactive_reason:
            status = "INACTIVE_LECTURER"
            status_label = f"Không tham gia giảng dạy ({inactive_reason})"
            status_badge_variant = "secondary"
            is_eligible = False
            details = f"Giảng viên không tham gia kỳ này ({inactive_reason})"
        elif cap_forbidden:
            status = "FORBIDDEN_CAPABILITY"
            status_label = "Bị loại — Bị cấm giảng dạy môn này"
            status_badge_variant = "danger"
            is_eligible = False
            details = f"Giảng viên bị đánh dấu cấm giảng dạy môn {section.course.name} ({section.course.code})"
        elif cap_not_confirmed:
            status = "CAPABILITY_NOT_CONFIRMED"
            status_label = "Bị loại — Năng lực chưa được xác nhận"
            status_badge_variant = "secondary"
            is_eligible = False
            details = f"Năng lực dạy môn {section.course.name} ({section.course.code}) chưa được phê duyệt chính thức"
        elif not has_cap:
            status = "NO_CAPABILITY"
            status_label = "Bị loại — Không đủ năng lực"
            status_badge_variant = "secondary"
            is_eligible = False
            details = f"Chưa có xác nhận năng lực dạy môn {section.course.name} ({section.course.code})"
        elif hard_unavailable:
            eq_course = cap_equiv_info.get(lec.id)
            eq_note = f" (Năng lực từ [{eq_course.code}] {eq_course.name})" if eq_course else ""
            status = "HARD_AVAILABILITY_CONFLICT"
            status_label = "Bị loại — Bận cứng"
            status_badge_variant = "danger"
            is_eligible = False
            details = (unavail_details or "Bận cứng vào khung giờ học của lớp này") + eq_note
        elif has_collision:
            eq_course = cap_equiv_info.get(lec.id)
            eq_note = f" (Năng lực từ [{eq_course.code}] {eq_course.name})" if eq_course else ""
            status = "TIMETABLE_COLLISION"
            status_label = "Bị loại — Trùng lịch"
            status_badge_variant = "warning"
            is_eligible = False
            first_col = collision_items[0]
            weeks_str = f"tuần {min(first_col['overlapping_weeks'])}-{max(first_col['overlapping_weeks'])}" if first_col["overlapping_weeks"] else ""
            details = f"Trùng lịch với lớp {first_col['class_code']} ({first_col['course_name']}) T{first_col['weekday']} {weeks_str}{eq_note}"
        elif workload_exceeded:
            eq_course = cap_equiv_info.get(lec.id)
            eq_note = f" (Năng lực từ [{eq_course.code}] {eq_course.name})" if eq_course else ""
            status = "WORKLOAD_EXCEEDED"
            status_label = "Bị loại — Vượt tải"
            status_badge_variant = "secondary"
            is_eligible = False
            details = workload_details + eq_note
        else:
            eq_course = cap_equiv_info.get(lec.id)
            eq_note = f" (Năng lực suy diễn từ [{eq_course.code}] {eq_course.name})" if eq_course else ""
            status = "ELIGIBLE"
            status_label = "Có thể phân công"
            status_badge_variant = "success"
            is_eligible = True
            details = f"Đủ năng lực môn{eq_note}, không bận cứng, không trùng lịch"

        analysis_rows.append({
            "lecturer_id": lec.id,
            "lecturer_name": lec.canonical_name,
            "lecturer_code": lec.code or "",
            "status": status,
            "status_label": status_label,
            "status_badge_variant": status_badge_variant,
            "is_eligible": is_eligible,
            "has_capability": has_cap,
            "hard_unavailable": hard_unavailable,
            "has_collision": has_collision,
            "conflicting_classes": collision_items,
            "preference_source": pref_source,
            "workload": {
                "teaching_groups": teaching_groups_count,
                "credits": credits_count,
            },
            "details": details,
            "is_currently_assigned": section.assigned_lecturer_id == lec.id,
            "is_locked_to_this": is_locked_to_this,
        })

    # Sort: Eligible first, then collisions, then hard unavailable, then capability issues, then inactive
    sort_rank = {
        "ELIGIBLE": 1,
        "TIMETABLE_COLLISION": 2,
        "HARD_AVAILABILITY_CONFLICT": 3,
        "WORKLOAD_EXCEEDED": 4,
        "CAPABILITY_NOT_CONFIRMED": 5,
        "NO_CAPABILITY": 6,
        "FORBIDDEN_CAPABILITY": 7,
        "INACTIVE_LECTURER": 8,
    }
    analysis_rows.sort(key=lambda r: (sort_rank.get(r["status"], 9), r["lecturer_name"]))

    course_info = {
        "id": section.course_id,
        "code": section.course.code if section.course else "",
        "name": section.course.name if section.course else "",
    }
    eligible_list = [
        {"lecturer_id": r["lecturer_id"], "lecturer_name": r["lecturer_name"], "status": r["status"]}
        for r in analysis_rows if r["is_eligible"]
    ]
    excluded_list = [
        {"lecturer_id": r["lecturer_id"], "lecturer_name": r["lecturer_name"], "status": r["status"], "reason": r["details"]}
        for r in analysis_rows if not r["is_eligible"]
    ]

    return CandidateAnalysisResult(
        analysis_rows,
        course=course_info,
        eligible=eligible_list,
        excluded=excluded_list,
    )


def get_unassigned_breakdown(
    db: Session, semester_id: int, run_id: int | None = None
) -> dict[str, int]:
    diagnostics = diagnose_unassigned_classes(db, semester_id, run_id)
    breakdown = {
        "total": len(diagnostics),
        "no_capability": sum(d["root_cause"] == "NO_CAPABILITY" for d in diagnostics),
        "hard_availability": sum(d["root_cause"] == "HARD_AVAILABILITY_CONFLICT" for d in diagnostics),
        "timetable_collision": sum(d["root_cause"] == "TIMETABLE_COLLISION" for d in diagnostics),
        "global_infeasibility": sum(d["root_cause"] == "GLOBAL_INFEASIBILITY" for d in diagnostics),
        "workload_limit": sum(d["root_cause"] == "WORKLOAD_HARD_LIMIT" for d in diagnostics),
        "locked_conflict": sum(d["root_cause"] == "LOCKED_CONFLICT" for d in diagnostics),
        "eligible_available": sum(d["root_cause"] == "ELIGIBLE_CANDIDATE_AVAILABLE" for d in diagnostics),
        "no_eligible": sum(d["root_cause"] == "NO_ELIGIBLE_LECTURER" for d in diagnostics),
        "data_quality": sum(d["root_cause"] == "DATA_QUALITY_BLOCKER" for d in diagnostics),
        "other": sum(d["root_cause"] == "UNKNOWN" for d in diagnostics),
    }
    return breakdown


def update_resolution_status(
    db: Session, semester_id: int, class_id: int, status: str, notes: str | None = None
) -> dict[str, Any]:
    section = db.scalar(
        select(ClassSection).where(ClassSection.id == class_id, ClassSection.semester_id == semester_id)
    )
    if not section:
        raise ValueError("Không tìm thấy lớp học phần.")

    section.resolution_status = status
    if notes is not None:
        section.resolution_notes = notes
    db.commit()
    return {
        "class_id": section.id,
        "resolution_status": section.resolution_status,
        "resolution_notes": section.resolution_notes,
    }


def override_lock_assignment(
    db: Session,
    semester_id: int,
    class_id: int,
    lecturer_id: int,
    reason: str,
    user: str = "Human Operator",
    lock: bool = True,
) -> dict[str, Any]:
    """Human-in-the-loop controlled lock override.

    The solver/machine must NEVER automatically suggest or break locks.
    Only explicit human intervention with an audit log can perform this action.
    """
    section = db.scalar(
        select(ClassSection).where(ClassSection.id == class_id, ClassSection.semester_id == semester_id)
    )
    if not section:
        raise ValueError("Không tìm thấy lớp học phần.")

    lecturer = db.get(Lecturer, lecturer_id)
    if not lecturer:
        raise ValueError("Không tìm thấy giảng viên.")

    if not reason or not reason.strip():
        raise ValueError("OVERRIDE_REASON_REQUIRED: Cần nhập lý do ghi đè phân công có kiểm soát.")

    previous_lecturer_id = section.assigned_lecturer_id
    was_locked = section.locked_assignment

    from app.models.entities import ValidationIssue
    audit_entry = ValidationIssue(
        semester_id=semester_id,
        severity="info",
        code="MANUAL_LOCK_OVERRIDE",
        message=f"Ghi đè khóa lớp {section.class_code} sang GV {lecturer.canonical_name}: {reason.strip()} (Bởi: {user})",
        details={
            "class_id": class_id,
            "previous_lecturer_id": previous_lecturer_id,
            "new_lecturer_id": lecturer_id,
            "was_locked": was_locked,
            "reason": reason.strip(),
            "performed_by": user,
        },
        raw_value=reason.strip(),
        resolution_status="RESOLVED",
    )
    db.add(audit_entry)

    # Update class section
    section.assigned_lecturer_id = lecturer_id
    section.assignment_source = "MANUAL_OVERRIDE"
    section.locked_assignment = lock
    section.resolution_status = "MANUALLY_RESOLVED"
    section.resolution_notes = f"Ghi đè phân công: {reason.strip()} (Bởi: {user})"

    # Update or add Assignment record for the latest run so UI reflects immediately
    run = latest_current_run(db, semester_id)
    if run and run.status in {"optimal", "feasible"}:
        existing_assignment = db.scalar(
            select(Assignment).where(Assignment.run_id == run.id, Assignment.class_id == class_id)
        )
        if existing_assignment:
            existing_assignment.lecturer_id = lecturer_id
            existing_assignment.locked = lock
            existing_assignment.source = "MANUAL_OVERRIDE"
        else:
            new_ass = Assignment(
                semester_id=semester_id,
                run_id=run.id,
                class_id=class_id,
                lecturer_id=lecturer_id,
                locked=lock,
                source="MANUAL_OVERRIDE",
            )
            db.add(new_ass)

        # Also remove this class from run.summary["unassigned"] if present
        if run.summary and isinstance(run.summary.get("unassigned"), list):
            run.summary["unassigned"] = [
                u for u in run.summary["unassigned"] if u.get("class_id") != class_id
            ]
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(run, "summary")

    db.commit()
    return {
        "success": True,
        "class_id": section.id,
        "class_code": section.class_code,
        "previous_lecturer_id": previous_lecturer_id,
        "new_lecturer_id": lecturer_id,
        "new_lecturer_name": lecturer.canonical_name,
        "locked": lock,
        "assignment_source": "MANUAL_OVERRIDE",
        "override_reason": reason.strip(),
        "audit_id": audit_entry.id,
    }
