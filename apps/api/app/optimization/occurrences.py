"""Calendar occurrences shared by availability checks and week-scoped rules."""
from datetime import date, timedelta


def meeting_occurrences(meeting, semester, target=None):
    """Return (week, date) pairs within every applicable inclusive date bound.

    Week one starts on the Monday containing the semester start. An empty
    week mask has no occurrences; it must not invent a week-one meeting.
    """
    target = target or {}
    scope=target.get('day_scope')
    allowed_days=({2,3,4,5,6} if scope=='ALL_WEEKDAYS' else {2,3,4,5,6,7,8} if scope=='ALL_DAYS' else {8} if scope=='CN' else {int(scope[1:])} if scope in {'T2','T3','T4','T5','T6','T7'} else None)
    if target.get('weekday') is not None: allowed_days={target['weekday']}
    if allowed_days is not None and meeting.weekday not in allowed_days: return []
    
    # Check meeting start/end against target start/end if both exist
    m_start = meeting.start_date if isinstance(getattr(meeting, 'start_date', None), date) else (date.fromisoformat(str(meeting.start_date)) if getattr(meeting, 'start_date', None) else None)
    m_end = meeting.end_date if isinstance(getattr(meeting, 'end_date', None), date) else (date.fromisoformat(str(meeting.end_date)) if getattr(meeting, 'end_date', None) else None)
    
    t_start = target['start_date'] if isinstance(target.get('start_date'), date) else (date.fromisoformat(str(target['start_date'])) if target.get('start_date') else None)
    t_end = target['end_date'] if isinstance(target.get('end_date'), date) else (date.fromisoformat(str(target['end_date'])) if target.get('end_date') else None)
    
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
