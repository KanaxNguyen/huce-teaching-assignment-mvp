from datetime import date, datetime, timedelta


def _to_date(val):
    if isinstance(val, date):
        return val
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(val), fmt).date()
        except Exception:
            pass
    try:
        return date.fromisoformat(str(val))
    except Exception:
        return None


def meeting_occurrences(meeting, semester, target=None):
    """Return (week, date) pairs within every applicable inclusive date bound.

    Week one starts on the Monday containing the semester start. An empty
    week mask has no occurrences; it must not invent a week-one meeting.
    """
    target = target or {}
    scope=target.get('day_scope')
    allowed_days=({2,3,4,5,6} if scope=='ALL_WEEKDAYS' else {2,3,4,5,6,7,8} if scope=='ALL_DAYS' else {8} if scope in {'CN', 'T8'} else {int(scope[1:])} if scope in {'T2','T3','T4','T5','T6','T7','T8'} else None)
    if target.get('weekday') is not None: allowed_days={target['weekday']}
    if allowed_days is not None and meeting.weekday not in allowed_days: return []
    
    # Check meeting start/end against target start/end if both exist
    m_start = _to_date(getattr(meeting, 'start_date', None))
    m_end = _to_date(getattr(meeting, 'end_date', None))
    
    t_start = _to_date(target.get('start_date'))
    t_end = _to_date(target.get('end_date'))
    
    if m_start and t_end and m_start > t_end:
        return []
    if m_end and t_start and m_end < t_start:
        return []
        
    anchor = getattr(semester, "start_date", None)
    monday = anchor - timedelta(days=anchor.weekday()) if anchor else None
    result = []
    
    target_weeks = set(target.get("weeks") or [])
    
    for week in sorted(set(meeting.active_weeks or [])):
        if target_weeks and week not in target_weeks:
            continue
            
        actual = monday + timedelta(weeks=week - 1, days=meeting.weekday - 2) if monday else None
        
        if actual:
            if m_start and actual < m_start:
                continue
            if m_end and actual > m_end:
                continue
            if t_start and actual < t_start:
                continue
            if t_end and actual > t_end:
                continue
            
        result.append((week, actual))
    return result


def meetings_overlap(left, right, semester=None) -> bool:
    """Compare actual occurrences; without an anchor use week/day conservatively."""
    if left.weekday != right.weekday or left.end_period < right.start_period or right.end_period < left.start_period:
        return False
    if semester is not None and semester.start_date:
        return bool({d for _, d in meeting_occurrences(left, semester)} &
                    {d for _, d in meeting_occurrences(right, semester)})
    if not set(left.active_weeks or []) & set(right.active_weeks or []):
        return False
    return not ((left.start_date and right.end_date and left.start_date > right.end_date) or
                (right.start_date and left.end_date and right.start_date > left.end_date))


def confirmed_merge(left, right) -> bool:
    return bool(left.merged_group_id and left.merged_group_id == right.merged_group_id and
                left.merged_confirmed and right.merged_confirmed and
                left.merge_status != "rejected" and right.merge_status != "rejected" and
                are_classes_mergeable(left, right))


def are_classes_mergeable(left, right) -> bool:
    """Validate whether two class sections can legitimately be merged.

    Classes can only be merged if:
    1. They belong to the same course (or equivalent curriculum course).
    2. Both classes have sessions defined.
    3. They have the same number of meeting sessions.
    4. Every session in `left` matches a session in `right` with the same
       weekday, periods, complete week masks and date bounds.
       Automatic suggestions additionally require matching rooms in the parser;
       explicit manual merging retains the existing room-override policy.
    """
    if getattr(left, "course_id", None) != getattr(right, "course_id", None):
        l_course = getattr(left, "course", None)
        r_course = getattr(right, "course", None)
        l_name = getattr(l_course, "name", "") if l_course else ""
        r_name = getattr(r_course, "name", "") if r_course else ""
        from unicodedata import category, normalize

        def _clean(t):
            norm = "".join(c for c in normalize("NFD", str(t or "").lower()) if category(c) != "Mn")
            return norm.replace("đ", "d").replace(" ", "")

        if not (l_name and r_name and _clean(l_name) == _clean(r_name)):
            return False

    l_sess = getattr(left, "sessions", []) or []
    r_sess = getattr(right, "sessions", []) or []
    if not l_sess or not r_sess:
        return False
    if len(l_sess) != len(r_sess):
        return False

    used_right = set()
    for s1 in l_sess:
        found = False
        for idx, s2 in enumerate(r_sess):
            if idx in used_right:
                continue
            if (s1.weekday == s2.weekday and s1.start_period == s2.start_period and
                    s1.end_period == s2.end_period and
                    s1.start_date == s2.start_date and s1.end_date == s2.end_date):
                w1 = set(s1.active_weeks or [])
                w2 = set(s2.active_weeks or [])
                if not w1 or w1 != w2:
                    continue
                used_right.add(idx)
                found = True
                break
        if not found:
            return False
    return len(used_right) == len(r_sess)
