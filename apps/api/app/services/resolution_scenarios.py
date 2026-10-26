"""Concrete, authority-ranked ways to staff a class the solver could not assign.

Every scenario states *who* may approve it, *what rule* it bends, and the exact
moves to make. Scenarios that only reshuffle inside the department without
breaking a hard rule come first; anything that bends a rule needs a named
approver and a written reason and is recorded in the audit log. A move that
would put a lecturer in two rooms at once is never offered.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.optimization.occurrences import are_classes_mergeable
from app.services.feasibility import REASON_LABELS
from app.services.manual_assignment import apply_manual_assignment, assignment_check_context, check_assignment_change

AUTHORITY = {
    1: {"approver": "Trưởng bộ môn", "label": "Trong quyền Trưởng bộ môn",
        "description": "Điều chỉnh trong bộ môn, không vi phạm ràng buộc cứng nào."},
    2: {"approver": "Trưởng bộ môn + giảng viên đồng ý", "label": "Cần giảng viên đồng ý",
        "description": "Vượt lịch bận hoặc định mức mà giảng viên đã đăng ký; phải có sự đồng ý của chính giảng viên."},
    3: {"approver": "Trưởng bộ môn (xác nhận chuyên môn)", "label": "Phê duyệt năng lực cho kỳ này",
        "description": "Giảng viên trong bộ môn chưa có năng lực ghi nhận cho môn này; Trưởng bộ môn xác nhận chuyên môn."},
    4: {"approver": "Trưởng khoa", "label": "Mượn giảng viên liên bộ môn",
        "description": "Giảng viên thuộc bộ môn khác; cần Trưởng khoa điều phối và bộ môn kia xác nhận lịch."},
    5: {"approver": "Phòng Đào tạo", "label": "Đổi lịch học hoặc mời thỉnh giảng",
        "description": "Không còn phương án trong khoa; đề nghị Phòng Đào tạo dời lịch lớp hoặc mời giảng viên thỉnh giảng."},
}

# Bending these needs the lecturer's own consent; physical clashes are never bendable.
CONSENT_REASONS = {"HARD_AVAILABILITY_CONFLICT", "HARD_PREFERENCE_CONFLICT", "MAX_WORKLOAD_EXCEEDED"}
PHYSICAL_REASONS = {"TIMETABLE_CONFLICT", "HARD_SEMINAR_CONFLICT", "LECTURER_INACTIVE", "LECTURER_NOT_PARTICIPATING",
                    "FORBIDDEN_ASSIGNMENT", "REQUIRED_ASSIGNMENT_CONFLICT", "MULTI_LECTURER_REVIEW",
                    "SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT", "TEACHING_GROUP_NOT_FOUND", "LECTURER_NOT_FOUND"}
MAX_OPTIONS = 4


def _load(context: dict, lecturer_id: int) -> dict[str, float]:
    groups = [g for cid, g in context["groups"].items() if context["state"].get(cid, (None,))[0] == lecturer_id]
    return {"classes": len(groups), "credits": round(sum(g.credits or 0 for g in groups), 1)}


def _labels(codes) -> list[str]:
    return [REASON_LABELS.get(code, code) for code in sorted(set(codes))]


def _option(context: dict, lecturer_id: int, *, bends=(), moves=None, note: str | None = None) -> dict[str, Any]:
    lecturer = context["lecturers"][lecturer_id]
    return {"lecturer_id": lecturer_id, "lecturer_name": lecturer.canonical_name, "lecturer_code": lecturer.code,
            "department": lecturer.department, "load": _load(context, lecturer_id),
            "bends": _labels(bends), "moves": moves or [], "note": note}


def _scenario(key: str, level: int, title: str, summary: str, options: list[dict], **extra) -> dict[str, Any]:
    # Prefer options that bend fewer rules, then the least loaded lecturer (keeps workload balanced).
    options = sorted(options, key=lambda o: (len(o["bends"]), len(o["moves"]), o["load"]["credits"]))
    return {"key": key, "level": level, "authority": AUTHORITY[level], "title": title, "summary": summary,
            "options": options[:MAX_OPTIONS], "available": bool(options) or key == "escalate", **extra}


def build_scenarios(db: Session, semester_id: int, class_id: int) -> dict[str, Any]:
    context = assignment_check_context(db, semester_id)
    group = context["groups"].get(class_id)
    if group is None:
        raise ValueError("Không tìm thấy lớp học phần.")
    semester = context["semester"]
    state = context["state"]
    checks = {lid: check_assignment_change(db, semester_id, class_id, lid, context=context)
              for lid, lecturer in context["lecturers"].items() if lecturer.status == "ACTIVE"}

    direct, swaps, consent, capability, borrow = [], [], [], [], []
    for lecturer_id, result in checks.items():
        codes = set(result["blocking_reasons"])
        if state.get(class_id, (None,))[0] == lecturer_id:
            continue
        if result["valid"]:
            direct.append(_option(context, lecturer_id))
            continue
        if codes == {"TIMETABLE_CONFLICT"}:
            swaps.extend(_swap_chains(db, semester_id, context, class_id, lecturer_id, result["affected_groups"]))
        elif codes and codes <= CONSENT_REASONS:
            consent.append(_option(context, lecturer_id, bends=codes))
        elif codes == {"COURSE_CAPABILITY_MISSING"}:
            capability.append(_option(context, lecturer_id, bends=codes))
        elif "LECTURER_DEPARTMENT_MISMATCH" in codes and not codes & PHYSICAL_REASONS:
            known = any(cap.lecturer_id == lecturer_id and cap.course_id == group.course_id and cap.allowed for cap in context["caps"])
            borrow.append(_option(context, lecturer_id, bends=codes - {"COURSE_CAPABILITY_MISSING"} if known else codes,
                                  note="Đã dạy môn này ở bộ môn khác." if known else "Chưa có năng lực ghi nhận cho môn này."))
    borrow.sort(key=lambda option: option["note"] != "Đã dạy môn này ở bộ môn khác.")

    merges = []
    for other in context["groups"].values():
        lecturer_id = state.get(other.id, (None,))[0]
        if other.id == class_id or lecturer_id is None or other.merged_group_id and other.merged_group_id == group.merged_group_id:
            continue
        if are_classes_mergeable(group, other):
            merges.append({**_option(context, lecturer_id, note=f"Ghép vào lớp {other.class_code} — dạy chung một buổi."),
                           "merge_with_class_id": other.id, "merge_with_class_code": other.class_code})

    scenarios = [
        _scenario("direct", 1, "Giao trực tiếp", "Các giảng viên này nhận được lớp ngay, không vi phạm ràng buộc nào.", direct),
        _scenario("swap", 1, "Đổi chéo trong bộ môn",
                  "Giảng viên có năng lực đang dạy lớp khác cùng giờ; chuyển lớp đó cho người khác rảnh để giải phóng họ.", swaps),
        _scenario("merge", 1, "Ghép lớp cùng môn cùng giờ",
                  "Lớp này học cùng giờ, cùng môn với một lớp đã có giảng viên; ghép để một giảng viên dạy chung.", merges),
        _scenario("consent", 2, "Xin giảng viên dạy ngoài nguyện vọng",
                  "Giảng viên có năng lực nhưng đã đăng ký bận / vượt định mức vào giờ này.", consent),
        _scenario("capability", 3, "Giao cho giảng viên chưa có năng lực ghi nhận",
                  "Giảng viên trong bộ môn đang rảnh nhưng chưa có năng lực dạy môn này trong danh mục.", capability),
        _scenario("borrow", 4, "Mượn giảng viên bộ môn khác",
                  "Giảng viên ngoài bộ môn; lịch dạy ở bộ môn của họ chưa có trong hệ thống nên cần xác nhận lại.", borrow),
        _scenario("escalate", 5, "Chuyển Phòng Đào tạo xử lý",
                  "Đề nghị dời lịch lớp sang ca có giảng viên rảnh, hoặc mời giảng viên thỉnh giảng.", []),
    ]
    blocked_summary = {}
    for lecturer_id, result in checks.items():
        for code in result["blocking_reasons"]:
            lecturer = context["lecturers"][lecturer_id]
            blocked_summary.setdefault(REASON_LABELS.get(code, code), []).append(
                f"{lecturer.canonical_name} ({lecturer.code})" if lecturer.code else lecturer.canonical_name)
    return {
        "class": {"id": group.id, "class_code": group.class_code, "course_code": group.course.code, "course_name": group.course.name,
                  "credits": group.credits, "current_lecturer_id": state.get(class_id, (None,))[0],
                  "sessions": [{"weekday": s.weekday, "start_period": s.start_period, "end_period": s.end_period,
                                "room": s.room, "active_weeks": s.active_weeks or []} for s in group.sessions]},
        "scenarios": scenarios,
        "recommended": next((s["key"] for s in scenarios if s["available"] and s["options"]), "escalate"),
        "why_blocked": [{"reason": reason, "lecturers": names} for reason, names in
                        sorted(blocked_summary.items(), key=lambda item: -len(item[1]))],
        "authority_ladder": [{"level": level, **info} for level, info in AUTHORITY.items()],
        "semester_id": semester.id,
    }


def _swap_chains(db, semester_id, context, class_id, lecturer_id, affected) -> list[dict]:
    """Free `lecturer_id` by moving each clashing (unlocked) class to another lecturer."""
    affected = sorted(set(affected))
    if not affected or len(affected) > 2 or any(context["groups"][cid].locked_assignment for cid in affected):
        return []
    state = dict(context["state"])
    moves = []
    for other_id in affected:
        replacement = None
        for other_lecturer in context["lecturers"]:
            if other_lecturer == lecturer_id or context["lecturers"][other_lecturer].status != "ACTIVE":
                continue
            trial = {**context, "state": state}
            if check_assignment_change(db, semester_id, other_id, other_lecturer, context=trial)["valid"]:
                replacement = other_lecturer
                break
        if replacement is None:
            return []
        state[other_id] = (replacement, "MANUAL", False)
        moves.append({"class_id": other_id, "class_code": context["groups"][other_id].class_code,
                      "from_lecturer_id": lecturer_id, "from_lecturer": context["lecturers"][lecturer_id].canonical_name,
                      "to_lecturer_id": replacement, "to_lecturer": context["lecturers"][replacement].canonical_name})
    final = check_assignment_change(db, semester_id, class_id, lecturer_id, context={**context, "state": state})
    if not final["valid"]:
        return []
    return [_option(context, lecturer_id, moves=moves)]


def apply_scenario(db: Session, semester_id: int, class_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.unassigned_diagnostics import override_lock_assignment, update_resolution_status
    key = payload.get("scenario")
    lecturer_id = payload.get("lecturer_id")
    reason = (payload.get("reason") or "").strip()
    approver = (payload.get("approver") or "").strip()
    scenario = next((s for s in build_scenarios(db, semester_id, class_id)["scenarios"] if s["key"] == key), None)
    if scenario is None:
        raise ValueError("Kịch bản không hợp lệ.")
    level = scenario["level"]
    option = next((o for o in scenario["options"] if o["lecturer_id"] == lecturer_id), None)
    if key not in {"escalate", "merge"} and option is None:
        raise ValueError("Giảng viên này không còn thuộc kịch bản đã chọn; dữ liệu đã thay đổi, hãy mở lại danh sách kịch bản.")
    if level >= 2 and (len(reason) < 5 or not approver):
        raise ValueError(f"Kịch bản này cần người phê duyệt ({AUTHORITY[level]['approver']}) và lý do tối thiểu 5 ký tự.")

    if key == "escalate":
        note = f"[Chuyển {AUTHORITY[5]['approver']}] {reason or 'Đề nghị dời lịch hoặc mời thỉnh giảng.'}" + (f" — {approver}" if approver else "")
        return {"applied": True, **update_resolution_status(db, semester_id, class_id, "ESCALATED", note)}
    if not isinstance(lecturer_id, int):
        raise ValueError("Cần chọn giảng viên.")

    if key == "direct":
        result = apply_manual_assignment(db, semester_id, class_id, lecturer_id, bool(payload.get("lock", False)))
    elif key == "swap":
        for move in option["moves"]:
            moved = apply_manual_assignment(db, semester_id, move["class_id"], move["to_lecturer_id"], False)
            if not moved["valid"]:
                raise ValueError(f"Không chuyển được lớp {move['class_code']}: {', '.join(_labels(moved['blocking_reasons']))}.")
        result = apply_manual_assignment(db, semester_id, class_id, lecturer_id, bool(payload.get("lock", False)))
    elif key == "merge":
        raise ValueError("Ghép lớp dùng chức năng ghép lớp hiện có.")
    else:
        check = check_assignment_change(db, semester_id, class_id, lecturer_id)
        physical = set(check["blocking_reasons"]) & PHYSICAL_REASONS
        if physical:
            raise ValueError("Không thể giao: " + ", ".join(_labels(physical)) + ".")
        result = override_lock_assignment(
            db, semester_id, class_id, lecturer_id,
            f"[{AUTHORITY[level]['label']} — phê duyệt: {approver}] {reason}", user=approver, lock=True)
        result["valid"] = True
    if not result.get("valid", False):
        raise ValueError("Không giao được: " + ", ".join(_labels(result.get("blocking_reasons", []))) + ".")
    return {"applied": True, "scenario": key, "level": level, **{k: v for k, v in result.items() if k != "valid"}}
