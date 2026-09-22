"""Authoritative draft structure and lifecycle contract for UI and apply."""
from datetime import date
from math import isfinite

SEMANTIC_FIELDS = {
    'lecturer_id', 'constraint_type', 'context_type', 'day_scope', 'periods',
    'start_date', 'end_date', 'numeric_value', 'hardness', 'weight', 'target', 'seminar_link',
}
SCOPES = {'T2','T3','T4','T5','T6','T7','CN','ALL_WEEKDAYS','ALL_DAYS'}
NUMERIC_TYPES = {'MIN_CLASSES','MAX_CLASSES','MAX_SESSIONS_PER_DAY','MAX_DAYS_PER_WEEK',
                 'MIN_FREE_MORNING_PER_WEEK','PREFER_CONSECUTIVE_PERIODS'}
DAY_TYPES = {'PREFERRED_DAYS','AVOID_DAYS'}
COMPACT_TYPES = {'PREFER_CONSECUTIVE_PERIODS','PREFER_COMPACT_SCHEDULE'}
TIME_TYPES = {'UNAVAILABLE','AVOID_PERIOD','PREFERRED_PERIOD','SEMINAR_COMMITMENT'}
SUPPORTED = TIME_TYPES | NUMERIC_TYPES | DAY_TYPES | COMPACT_TYPES | {'PREFER_LOW_WORKLOAD','REQUIRED_ASSIGNMENT','FORBIDDEN_ASSIGNMENT','SHARED_SEMINAR'}
TRANSITIONS = {
    'DRAFT': {'DRAFT','NEEDS_REVIEW','CONFIRMED','REJECTED'},
    'NEEDS_REVIEW': {'DRAFT','NEEDS_REVIEW','CONFIRMED','REJECTED'},
    'CONFIRMED': {'CONFIRMED','NEEDS_REVIEW','REJECTED'},
    'REJECTED': {'REJECTED','NEEDS_REVIEW'},
}


def values(item):
    if isinstance(item, dict): return item
    return {key: getattr(item,key,None) for key in SEMANTIC_FIELDS | {'status','draft_kind','participant_codes'}}


def validate_preference_draft(item, db=None):
    data=values(item); errors=[]; warnings=[]
    def error(code,field,message): errors.append({'code':code,'field':field,'message':message})
    kind=data.get('constraint_type'); target=data.get('target') or {}
    if not isinstance(target,dict):
        error('INVALID_TARGET','target','Đích ràng buộc phải là một đối tượng có cấu trúc.'); target={}
    if target.get('_stale_source_reference'): error('SOURCE_CHANGED_REVIEW_REQUIRED','target','Nguồn đã đổi; giữ bản cũ để đối chiếu và tạo bản nháp mới với nguồn hiện hành.')
    if not isinstance(kind,str): kind=None
    for field in ('context_type','day_scope','hardness'):
        if data.get(field) is not None and not isinstance(data[field],str):
            error('INVALID_FIELD',field,'Giá trị phải là văn bản.'); data={**data,field:None}
    if kind not in SUPPORTED: error('UNSUPPORTED_CONSTRAINT_TYPE','constraint_type','Loại này chỉ để rà soát; hãy diễn giải thành ràng buộc được hỗ trợ.')
    if data.get('context_type') not in {'TEACHING','SEMINAR'}:
        error('INVALID_CONTEXT','context_type','Cần chọn ngữ cảnh cụ thể hoặc tách câu ghép.')
    elif (kind in {'SEMINAR_COMMITMENT','SHARED_SEMINAR'}) != (data.get('context_type')=='SEMINAR') and kind in SUPPORTED:
        error('CONTEXT_TYPE_MISMATCH','context_type','Loại ràng buộc không phù hợp ngữ cảnh.')
    if kind=='SHARED_SEMINAR':
        members=target.get('member_ids') or []
        if not isinstance(members,list):
            error('INVALID_MEMBERS','lecturer_id','Danh sách người tham gia không hợp lệ.'); members=[]
        target={**target,'member_ids':members}
        if not members or len(members)!=len(data.get('participant_codes') or members): error('MISSING_LECTURER','lecturer_id','Chưa xác định đủ người tham gia seminar.')
        scopes=target.get('day_scopes')
        if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or s not in SCOPES for s in scopes): error('MISSING_DAY','day_scope','Chưa xác định ngày seminar.')
        ranges=target.get('period_blocks') or []
    else:
        if not data.get('lecturer_id'): error('MISSING_LECTURER','lecturer_id','Chưa xác định giảng viên; không thể áp dụng toàn bộ giảng viên.')
        ranges=target.get('period_alternatives') or [data.get('periods') or []]
    if db is not None:
        from app.models.entities import Lecturer, ClassSection
        identities=target.get('member_ids',[]) if kind=='SHARED_SEMINAR' else [data.get('lecturer_id')]
        if any(i is not None and (not isinstance(i,int) or isinstance(i,bool) or db.get(Lecturer,i) is None) for i in identities): error('UNKNOWN_LECTURER','lecturer_id','Giảng viên không tồn tại.')
        if kind in {'REQUIRED_ASSIGNMENT','FORBIDDEN_ASSIGNMENT'}:
            class_id=target.get('class_id')
            group=db.get(ClassSection,class_id) if isinstance(class_id,int) else None
            semester_id=item.get('semester_id') if isinstance(item,dict) else item.semester_id
            if not group or group.semester_id!=semester_id: error('INVALID_TARGET','target','Chọn TeachingGroup thuộc kỳ học hiện tại.')
    if not isinstance(ranges,list) or any(not isinstance(r,list) for r in ranges):
        error('INVALID_PERIOD','periods','Danh sách tiết không hợp lệ.'); ranges=[]
    if kind in TIME_TYPES | {'SHARED_SEMINAR'}:
        if not ranges or any(not p for p in ranges): error('MISSING_PERIOD','periods','Chưa xác định tiết; không tự điền khung giờ.')
    if any(not isinstance(p,int) or isinstance(p,bool) or not 1<=p<=15 for r in ranges for p in r): error('INVALID_PERIOD','periods','Tiết phải là số nguyên từ 1 đến 15.')
    scope=data.get('day_scope')
    if scope and scope not in SCOPES: error('INVALID_DAY','day_scope','Phạm vi ngày không hợp lệ.')
    if kind in DAY_TYPES:
        days=target.get('weekdays') or []
        if not isinstance(days,list) or not days or any(not isinstance(d,int) or d < 2 or d > 8 for d in days):
            error('MISSING_DAY','day_scope','Cần chọn ít nhất một thứ hợp lệ.')
    if kind in TIME_TYPES and not (scope in SCOPES or (data.get('start_date') and data.get('end_date'))):
        error('MISSING_DAY','day_scope','Chưa xác định ngày hoặc khoảng ngày áp dụng.')
    dates=[]
    for field in ('start_date','end_date'):
        raw=data.get(field)
        try:
            parsed=date.fromisoformat(raw) if isinstance(raw,str) and raw else raw or None
            if parsed is not None and not isinstance(parsed,date): raise ValueError()
            dates.append(parsed)
        except (ValueError,TypeError): dates.append(None); error('INVALID_DATE',field,'Ngày không hợp lệ.')
    if all(dates) and dates[0]>dates[1]: error('INVALID_DATE_RANGE','end_date','Ngày kết thúc phải không trước ngày bắt đầu.')
    if kind in NUMERIC_TYPES:
        number=data.get('numeric_value')
        if number is None: number=target.get('value',target.get('max',target.get('min')))
        minimum=0 if kind in {'MIN_CLASSES','MAX_CLASSES'} else 1
        if isinstance(number,bool) or not isinstance(number,(int,float)) or not isfinite(number) or number<minimum or number!=int(number):
            error('INVALID_NUMERIC_VALUE','numeric_value',f'Cần giá trị số nguyên từ {minimum} trở lên.')
        elif kind=='MIN_FREE_MORNING_PER_WEEK' and number>5: error('INVALID_NUMERIC_VALUE','numeric_value','Tối đa 5 buổi sáng T2–T6 mỗi tuần.')
    if kind in {'REQUIRED_ASSIGNMENT','FORBIDDEN_ASSIGNMENT'} and not isinstance(target.get('class_id'),int): error('MISSING_TARGET','target','Chưa chọn TeachingGroup.')
    if data.get('hardness') not in {'hard','soft'}: error('MISSING_HARDNESS','hardness','Chọn HARD hoặc SOFT.')
    weight=data.get('weight')
    if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not isfinite(weight) or not 0<=weight<=1: error('INVALID_WEIGHT','weight','Chọn trọng số trong 0–1; số 0 được giữ nguyên.')
    if data.get('status')=='REJECTED': error('PREFERENCE_RESTORE_REQUIRED','status','Khôi phục về Cần xác nhận trước khi xác nhận lại.')
    return {'is_confirmable':not errors,'validation_errors':errors,'validation_warnings':warnings}


def transition_status(old_status, requested, semantic_changed=False):
    requested=requested or old_status
    if requested not in TRANSITIONS.get(old_status,set()):
        raise ValueError('PREFERENCE_INVALID_TRANSITION')
    if old_status=='CONFIRMED' and semantic_changed and requested!='REJECTED':
        return 'NEEDS_REVIEW'
    return requested


def field_provenance(item):
    data=values(item); saved=(data.get('target') or {}).get('_provenance',{})
    return {key:saved.get(key,{'origin':'UNKNOWN'}) for key in SEMANTIC_FIELDS-{'target'}}
