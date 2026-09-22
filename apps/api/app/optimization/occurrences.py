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
