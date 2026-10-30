"""Pre-solve feasibility check.

Finds problems that make some classes impossible to assign (or make the whole
CP-SAT model infeasible) *before* the solver runs, using only the same hard
rules the solver and the manual checker enforce. Every finding is a proven
consequence of hard data, never a guess:

* a class with no lecturer who passes the hard checks can never be assigned;
* at any single moment a lecturer teaches at most one class, so if more classes
  meet at the same moment than distinct capable lecturers can cover (maximum
  bipartite matching, Hall's theorem) some of them must stay unassigned;
* contradictory locks / hard minimums / hard seminars make the model infeasible.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.optimization.occurrences import confirmed_merge, meeting_occurrences
from app.optimization.solver import _event_slots, _normalized_type, _overlap, _slot_match
from app.services.manual_assignment import OVERRIDE_BYPASSABLE, assignment_check_context, check_assignment_change

BLOCKS = ((1, 3), (4, 6), (7, 9), (10, 12), (13, 15))

REASON_LABELS = {
    "COURSE_CAPABILITY_MISSING": "chưa có năng lực dạy môn",
    "LECTURER_DEPARTMENT_MISMATCH": "thuộc bộ môn khác",
    "LECTURER_INACTIVE": "không còn hoạt động",
    "LECTURER_NOT_PARTICIPATING": "không tham gia kỳ này",
    "HARD_AVAILABILITY_CONFLICT": "đăng ký bận cứng",
    "HARD_PREFERENCE_CONFLICT": "chỉ nhận dạy khung giờ khác",
    "TIMETABLE_CONFLICT": "trùng lịch với lớp khác",
    "MAX_WORKLOAD_EXCEEDED": "vượt định mức tải cứng",
    "HARD_SEMINAR_CONFLICT": "trùng seminar bắt buộc",
    "FORBIDDEN_ASSIGNMENT": "bị cấm dạy lớp này",
    "REQUIRED_ASSIGNMENT_CONFLICT": "lớp đã bắt buộc giao cho người khác",
    "MULTI_LECTURER_REVIEW": "lớp đang chờ rà soát nhiều giảng viên",
    "SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT": "lớp cần chia giảng viên theo buổi",
}


def _block_index(period: int) -> int:
    return next(index for index, (start, end) in enumerate(BLOCKS) if start <= period <= end) if 1 <= period <= 15 else 4


def static_candidates(db: Session, semester_id: int, context: dict | None = None) -> tuple[dict, dict, dict]:
    """Candidates per class against hard rules and *locked* assignments only.

    Returns (candidates, blocking reasons per class/lecturer, the check context).
    Unlocked assignments are ignored: the solver is free to move them.
    """
    context = context or assignment_check_context(db, semester_id)
    groups = context["groups"]
    locked_state = {
        group.id: (group.assigned_lecturer_id, group.assignment_source, True)
        for group in groups.values() if group.locked_assignment and group.assigned_lecturer_id
    }
    static_context = {**context, "state": locked_state}
    candidates: dict[int, set[int]] = {}
    reasons: dict[int, dict[int, list[str]]] = {}
    for class_id, group in groups.items():
        candidates[class_id] = set()
        reasons[class_id] = {}
        for lecturer_id, lecturer in context["lecturers"].items():
            if lecturer.status != "ACTIVE":
                continue
            result = check_assignment_change(db, semester_id, class_id, lecturer_id, context=static_context)
            approved_exception = (group.locked_assignment and group.assignment_source == "MANUAL_OVERRIDE"
                                  and group.assigned_lecturer_id == lecturer_id
                                  and not set(result["blocking_reasons"]) - OVERRIDE_BYPASSABLE)
            if result["valid"] or approved_exception:
                candidates[class_id].add(lecturer_id)
            else:
                reasons[class_id][lecturer_id] = sorted(set(result["blocking_reasons"]))
    return candidates, reasons, static_context


def _max_matching(class_ids: list[int], candidates: dict[int, set[int]]) -> tuple[int, set[int], set[int]]:
    """Kuhn's augmenting-path maximum bipartite matching (sizes here are tiny).

    Returns (matched size, S, N(S)) where S is a set of classes that needs more
    lecturers than its candidate set N(S) holds (a Hall violator): the concrete
    "these k classes share only these j lecturers" explanation for a shortage.
    """
    owner: dict[int, int] = {}

    def augment(class_id: int, seen: set[int]) -> bool:
        for lecturer_id in candidates.get(class_id, ()):  # noqa: B007 - recursion over neighbours
            if lecturer_id in seen:
                continue
            seen.add(lecturer_id)
            if lecturer_id not in owner or augment(owner[lecturer_id], seen):
                owner[lecturer_id] = class_id
                return True
        return False

    unmatched = [class_id for class_id in class_ids if not augment(class_id, set())]
    tight_classes, tight_lecturers, queue = set(unmatched), set(), list(unmatched)
    while queue:
        for lecturer_id in candidates.get(queue.pop(), ()):
            if lecturer_id in tight_lecturers:
                continue
            tight_lecturers.add(lecturer_id)
            matched_class = owner.get(lecturer_id)
            if matched_class is not None and matched_class not in tight_classes:
                tight_classes.add(matched_class)
                queue.append(matched_class)
    return len(class_ids) - len(unmatched), tight_classes, tight_lecturers


def precheck(db: Session, semester_id: int) -> dict[str, Any]:
    context = assignment_check_context(db, semester_id)
    semester = context.get("semester")
    groups = context.get("groups", {})
    items: list[dict[str, Any]] = []

    def add(code: str, severity: str, title: str, detail: str, class_ids=(), suggestion: str | None = None, **extra):
        items.append({
            "code": code, "severity": severity, "title": title, "detail": detail,
            "class_ids": list(class_ids), "class_codes": [groups[i].class_code for i in class_ids if i in groups],
            "suggestion": suggestion, **extra,
        })

    if semester is None or not groups:
        add("NO_CLASSES", "blocking", "Chưa có lớp học phần", "Cần kích hoạt nguồn lịch học trước khi phân công.")
        return _result(items, [], [], {}, 0, 0)
    if semester.active_schedule_source_id is None:
        add("NO_ACTIVE_SCHEDULE", "blocking", "Chưa kích hoạt nguồn lịch học",
            "Solver chỉ chạy trên nguồn lịch đã được đối chiếu và xác nhận.")

    _check_semester_dates(semester, groups, add)

    candidates, reasons, _ = static_candidates(db, semester_id, context)
    lecturers = context["lecturers"]

    # Confirmed merged classes are taught together: count each merged group once.
    representative: dict[int, int] = {}
    ordered = sorted(groups)
    for index, class_id in enumerate(ordered):
        representative.setdefault(class_id, class_id)
        for other_id in ordered[index + 1:]:
            if other_id not in representative and confirmed_merge(groups[class_id], groups[other_id]):
                representative[other_id] = representative[class_id]

    # 1. Classes nobody can ever teach.
    zero = [class_id for class_id in ordered if representative[class_id] == class_id and not candidates[class_id]]
    no_capability = [c for c in zero if all("COURSE_CAPABILITY_MISSING" in r or "LECTURER_DEPARTMENT_MISMATCH" in r
                                            for r in reasons[c].values())]
    blocked = [c for c in zero if c not in no_capability]
    if no_capability:
        courses = sorted({f"{groups[c].course.code} – {groups[c].course.name}" for c in no_capability})
        add("NO_CAPABLE_LECTURER", "warning", f"{len(no_capability)} lớp không có giảng viên nào đủ năng lực",
            "Môn: " + "; ".join(courses[:6]) + ("…" if len(courses) > 6 else ""), no_capability,
            "Nạp ma trận năng lực / phân công lịch sử, hoặc dùng kịch bản mượn giảng viên liên bộ môn.")
    if blocked:
        add("ALL_CAPABLE_BLOCKED", "warning", f"{len(blocked)} lớp có giảng viên đủ năng lực nhưng tất cả đều vướng",
            "Mọi giảng viên có năng lực đều đăng ký bận cứng, vượt định mức hoặc trùng lớp đã khóa vào giờ này.",
            blocked, "Xem kịch bản: xin giảng viên đồng ý dạy ngoài nguyện vọng hoặc đổi chéo lớp.")

    # 2. Locks that contradict each other or the hard rules make the solver stop.
    for index, class_id in enumerate(ordered):
        group = groups[class_id]
        if not (group.locked_assignment and group.assigned_lecturer_id):
            continue
        if group.assigned_lecturer_id not in candidates[class_id]:
            why = ", ".join(REASON_LABELS.get(code, code) for code in reasons[class_id].get(group.assigned_lecturer_id, []))
            add("LOCKED_ASSIGNMENT_INVALID", "blocking", f"Lớp {group.class_code} đang khóa cho giảng viên không hợp lệ",
                f"{lecturers[group.assigned_lecturer_id].canonical_name}: {why or 'vi phạm ràng buộc cứng'}.", [class_id],
                "Mở khóa lớp hoặc sửa ràng buộc của giảng viên trước khi chạy.")
        for other_id in ordered[index + 1:]:
            other = groups[other_id]
            if (other.locked_assignment and other.assigned_lecturer_id == group.assigned_lecturer_id
                    and not confirmed_merge(group, other)
                    and any(_overlap(a, b, semester) for a in group.sessions for b in other.sessions)):
                add("LOCKED_ASSIGNMENT_CONFLICT", "blocking", f"Hai lớp khóa trùng giờ: {group.class_code} và {other.class_code}",
                    f"Cùng giao cho {lecturers[group.assigned_lecturer_id].canonical_name} và trùng lịch.", [class_id, other_id],
                    "Mở khóa một trong hai lớp, hoặc xác nhận ghép lớp nếu đây là lớp ghép.")

    # 3. Hard rules that the model cannot satisfy at all (CP-SAT would return INFEASIBLE).
    for constraint in context["constraints"]:
        if constraint.hardness != "hard" or not constraint.lecturer_id:
            continue
        kind = _normalized_type(constraint.constraint_type)
        target = constraint.target or {}
        name = lecturers.get(constraint.lecturer_id).canonical_name if constraint.lecturer_id in lecturers else f"#{constraint.lecturer_id}"
        if kind == "MIN_CLASSES" and isinstance(target.get("min"), int):
            possible = sum(1 for c in ordered if representative[c] == c and constraint.lecturer_id in candidates[c])
            if possible < target["min"]:
                add("HARD_MIN_UNREACHABLE", "blocking", f"{name}: bắt buộc tối thiểu {target['min']} lớp nhưng chỉ dạy được {possible}",
                    "Ràng buộc cứng này khiến toàn bộ mô hình vô nghiệm.", [], "Chuyển ràng buộc sang mềm hoặc giảm số lớp tối thiểu.")
        if kind == "REQUIRED_ASSIGNMENT" and isinstance(target.get("class_id"), int):
            class_id = target["class_id"]
            if class_id in groups and constraint.lecturer_id not in candidates[class_id]:
                why = ", ".join(REASON_LABELS.get(code, code) for code in reasons[class_id].get(constraint.lecturer_id, []))
                add("REQUIRED_ASSIGNMENT_IGNORED", "warning", f"Ràng buộc bắt buộc {name} dạy {groups[class_id].class_code} sẽ bị bỏ qua",
                    f"Giảng viên không thể nhận lớp này: {why}.", [class_id], "Sửa ràng buộc hoặc dữ liệu năng lực/lịch bận.")
    for seminar in context["seminars"]:
        members = [m for m in (seminar.members or []) if isinstance(m, int)]
        slots = _event_slots(seminar)
        if seminar.hardness != "hard" or not members or not slots:
            continue
        locked_member_groups = [g for g in groups.values() if g.locked_assignment and g.assigned_lecturer_id in members]
        if all(any(_slot_match(s, slot, semester) for g in locked_member_groups for s in g.sessions) for slot in slots):
            add("HARD_SEMINAR_IMPOSSIBLE", "blocking", f"Seminar bắt buộc “{seminar.name}” không còn khung nào trống",
                "Mọi khung cho phép đều trùng lớp đã khóa của ít nhất một thành viên.", [],
                "Thêm khung giờ, chuyển seminar sang mềm, hoặc mở khóa lớp trùng.")

    # 4. Moment-by-moment capacity (Hall's theorem): classes meeting at the same moment
    #    need distinct lecturers. Zero-candidate classes are already reported above.
    by_moment: dict[tuple, set[int]] = defaultdict(set)
    moment_meta: dict[tuple, tuple[int, int, int]] = {}
    for class_id in ordered:
        rep = representative[class_id]
        if rep != class_id or not candidates[class_id]:
            continue
        for session in groups[class_id].sessions:
            for week, actual in meeting_occurrences(session, semester):
                for period in range(session.start_period, session.end_period + 1):
                    key = (actual, period)
                    by_moment[key].add(class_id)
                    moment_meta[key] = (session.weekday, week, period)
    shortages: dict[frozenset, dict[str, Any]] = {}
    heat: dict[tuple[int, int], dict[str, int]] = {}
    matched_cache: dict[frozenset, tuple[int, set[int], set[int]]] = {}
    for key, members in by_moment.items():
        weekday, week, period = moment_meta[key]
        cell = heat.setdefault((weekday, _block_index(period)), {"demand": 0, "capable": 0, "deficit": 0})
        frozen = frozenset(members)
        if frozen not in matched_cache:
            matched_cache[frozen] = _max_matching(sorted(members), candidates) if len(members) > 1 else (len(members), set(), set())
        matched, tight_classes, tight_lecturers = matched_cache[frozen]
        deficit = len(members) - matched
        union = set().union(*(candidates[c] for c in members))
        if len(members) > cell["demand"]:
            cell.update(demand=len(members), capable=len(union))
        cell["deficit"] = max(cell["deficit"], deficit)
        if deficit > 0:
            entry = shortages.setdefault(frozen, {"weekday": weekday, "periods": set(), "weeks": set(), "deficit": deficit,
                                                  "class_ids": sorted(tight_classes), "lecturer_ids": sorted(tight_lecturers),
                                                  "simultaneous": len(members)})
            entry["periods"].add(period)
            entry["weeks"].add(week)
    shortage_list = []
    for entry in sorted(shortages.values(), key=lambda e: (-e["deficit"], e["weekday"], min(e["periods"]))):
        periods = sorted(entry["periods"])
        shortage_list.append({
            "weekday": entry["weekday"], "start_period": periods[0], "end_period": periods[-1],
            "weeks": sorted(entry["weeks"]), "deficit": entry["deficit"], "simultaneous": entry["simultaneous"],
            "class_ids": entry["class_ids"], "class_codes": [groups[c].class_code for c in entry["class_ids"]],
            "lecturers": [lecturers[l].canonical_name for l in entry["lecturer_ids"] if l in lecturers],
        })
    # Keep the clearest hotspots; nested period ranges of one clash repeat the same story.
    distinct, seen_cells = [], set()
    for shortage in shortage_list:
        cell = (shortage["weekday"], _block_index(shortage["start_period"]), tuple(shortage["class_ids"]))
        if cell in seen_cells:
            continue
        seen_cells.add(cell)
        distinct.append(shortage)
    for shortage in distinct[:6]:
        add("SLOT_SHORTAGE", "warning",
            f"Thứ {shortage['weekday']} tiết {shortage['start_period']}–{shortage['end_period']}: thiếu {shortage['deficit']} giảng viên",
            f"{len(shortage['class_ids'])} lớp ({', '.join(shortage['class_codes'][:6])}) chỉ có chung "
            f"{len(shortage['lecturers'])} giảng viên đủ điều kiện ({', '.join(shortage['lecturers'][:6]) or 'không ai'}) "
            f"— tuần {_weeks_text(shortage['weeks'])}.", shortage["class_ids"],
            "Ghép lớp cùng môn cùng giờ, mượn giảng viên, hoặc đề nghị Phòng Đào tạo dời một lớp sang ca khác.")

    unconfirmed = {g.merged_group_id for g in groups.values() if g.merged_group_id and not g.merged_confirmed
                   and getattr(g, "merge_status", "") not in {"confirmed", "rejected"}}
    if unconfirmed:
        add("UNCONFIRMED_MERGES", "info", f"{len(unconfirmed)} nhóm lớp ghép đề xuất chưa được xác nhận",
            "Lớp ghép chưa xác nhận được coi là hai lớp riêng, cần hai giảng viên nếu trùng giờ.", [],
            "Xác nhận ở tab Lớp ghép, hoặc bật tùy chọn coi nhóm đề xuất là đã xác nhận khi chạy.")

    max_deficit = max((s["deficit"] for s in distinct), default=0)
    heatmap = [{"weekday": d, "block": b, **values} for (d, b), values in sorted(heat.items())]
    return _result(items, distinct, heatmap, {
        "classes": len(ordered),
        "lecturers": sum(1 for l in lecturers.values() if l.status == "ACTIVE"),
        "zero_candidate_classes": len(zero),
        "single_candidate_classes": sum(1 for c in ordered if representative[c] == c and len(candidates[c]) == 1),
        "unconfirmed_merge_groups": len(unconfirmed),
    }, len(zero) + max_deficit, len(zero))


def _check_semester_dates(semester, groups: dict, add) -> None:
    """Week numbers in the source are counted from the semester start date.

    If the semester dates do not match the file (e.g. the file counts weeks from
    03/08 but the semester starts 07/09), every week-to-date conversion is
    shifted: the solver then misses real clashes and may double-book lecturers.
    """
    from datetime import date, timedelta
    sessions = [session for group in groups.values() for session in group.sessions]
    dated = [s for s in sessions if s.start_date or s.end_date]
    if not dated or not semester.start_date:
        return
    def as_date(value):
        return value if isinstance(value, date) or value is None else date.fromisoformat(str(value))
    outside = [s for s in dated if (as_date(s.start_date) and as_date(s.start_date) < semester.start_date)
               or (as_date(s.end_date) and semester.end_date and as_date(s.end_date) > semester.end_date)]
    if not outside:
        return
    earliest = min(as_date(s.start_date) for s in dated if s.start_date)
    latest = max((as_date(s.end_date) for s in dated if s.end_date), default=None)
    suggested = earliest - timedelta(days=earliest.weekday())
    share = len(outside) / len(dated)
    add("SEMESTER_DATES_MISMATCH", "blocking" if share >= 0.05 else "warning",
        f"Ngày của kỳ học không khớp với lịch trong file ({len(outside)}/{len(dated)} buổi nằm ngoài kỳ)",
        (f"Kỳ học đặt {semester.start_date:%d/%m/%Y}–{semester.end_date:%d/%m/%Y}" if semester.end_date
         else f"Kỳ học bắt đầu {semester.start_date:%d/%m/%Y}") + f", nhưng file có buổi học từ {earliest:%d/%m/%Y}.",
        [], f"Hệ thống không cho đổi mốc tuần khi kỳ đã có lịch. Tạo kỳ mới với ngày bắt đầu {suggested:%d/%m/%Y}"
        + (f" và ngày kết thúc ≥ {latest:%d/%m/%Y}" if latest else "")
        + " ở bước Kỳ học rồi nhập lại hai file. Nếu để nguyên, số tuần bị quy đổi lệch ngày và solver có thể xếp một giảng viên dạy hai lớp cùng lúc.")


def _weeks_text(weeks: list[int]) -> str:
    if not weeks:
        return "—"
    ranges, start, previous = [], weeks[0], weeks[0]
    for week in weeks[1:] + [None]:
        if week is not None and week == previous + 1:
            previous = week
            continue
        ranges.append(f"{start}–{previous}" if start != previous else str(start))
        if week is not None:
            start = previous = week
    return ", ".join(ranges)


def _result(items, shortages, heatmap, stats, estimated, zero) -> dict[str, Any]:
    severity_rank = {"blocking": 0, "warning": 1, "info": 2}
    items.sort(key=lambda item: severity_rank[item["severity"]])
    blocking = any(item["severity"] == "blocking" for item in items)
    return {
        "status": "blocking" if blocking else "warning" if any(i["severity"] == "warning" for i in items) else "ok",
        "can_run": not blocking,
        # Lower bound: zero-candidate classes plus the worst single-moment shortage.
        "estimated_min_unassigned": estimated,
        "items": items,
        "shortages": shortages,
        "heatmap": heatmap,
        "stats": stats,
    }
