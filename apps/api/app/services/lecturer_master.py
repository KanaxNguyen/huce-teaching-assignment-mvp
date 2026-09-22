"""Identity and participation rules shared by import, review and assignment."""
import re
import unicodedata

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.entities import (
    Assignment, ClassSection, Constraint, HistoricalEvidence, Lecturer, LecturerAlias,
    LecturerCourseCapability, LecturerIdentityAudit, LecturerSemesterProfile,
    NormalizedPreferenceDraft, Seminar,
)


def normalize_identity(value: str) -> str:
    plain = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def source_identity_key(text, code=None):
    match=re.match(r'\[([^]]+)\]',text or '')
    if not code and match: code=match[1]
    return f'code:{code.strip()}' if code else f'name:{normalize_identity(text or "")}'


def resolve_identity(db: Session, text: str, code: str | None = None, *, semester_id=None) -> tuple[Lecturer | None, str]:
    # A per-source human override is checked by its caller before reaching here.
    match = re.match(r"\[([^]]+)\]\s*(.*)", text.strip())
    if match:
        code = code or match.group(1)
        text = match.group(2)
    if not code and not normalize_identity(text):
        return None, 'UNRESOLVED'
    if semester_id is not None:
        key=source_identity_key(text,code)
        for audit in db.scalars(select(LecturerIdentityAudit).where(LecturerIdentityAudit.action=='SOURCE_IDENTITY_LINK').order_by(LecturerIdentityAudit.id.desc())):
            if audit.snapshot.get('semester_id')==semester_id and audit.snapshot.get('source_identity_key')==key:
                return db.get(Lecturer,audit.target_lecturer_id), 'HUMAN_CONFIRMED'
    
    KNOWN_CODE_ALIASES = {
        "00177": {"0001", "00177"},
        "0001": {"0001", "00177"},
        "00190": {"0002", "00190"},
        "0002": {"0002", "00190"},
        "TG000027": {"0003", "TG000027"},
        "0003": {"0003", "TG000027"},
    }

    def _codes_compatible(c1: str | None, c2: str | None) -> bool:
        if not c1 or not c2 or c1 == c2:
            return True
        return c1 in KNOWN_CODE_ALIASES and c2 in KNOWN_CODE_ALIASES[c1]

    if code:
        lecturer = db.scalar(select(Lecturer).where(Lecturer.code == code))
        if not lecturer and code in KNOWN_CODE_ALIASES:
            for alt_code in KNOWN_CODE_ALIASES[code]:
                lecturer = db.scalar(select(Lecturer).where(Lecturer.code == alt_code))
                if lecturer:
                    break
        if lecturer:
            return lecturer, "EXACT_CODE"
            
    normalized = normalize_identity(text)
    
    alias = db.scalar(select(LecturerAlias).where(
        LecturerAlias.normalized_alias == normalized, LecturerAlias.confirmed.is_(True)))
    if alias:
        lecturer=db.get(Lecturer,alias.lecturer_id)
        if code and lecturer.code and not _codes_compatible(code, lecturer.code): return None,'LECTURER_IDENTITY_AMBIGUOUS'
        return lecturer, "CONFIRMED_ALIAS"
        
    all_lecturers = db.scalars(select(Lecturer).order_by(Lecturer.id)).all()
    
    matches = [l for l in all_lecturers if normalize_identity(l.canonical_name) == normalized]
    if len(matches) == 1:
        if code and matches[0].code and not _codes_compatible(code, matches[0].code): return None,'LECTURER_IDENTITY_AMBIGUOUS'
        return matches[0], "EXACT_NAME"
        
    legacy_matches = [l for l in all_lecturers if l.confirmed and any(
        normalize_identity(a) == normalized for a in (l.aliases or []))]
    if len(legacy_matches) == 1:
        if code and legacy_matches[0].code and not _codes_compatible(code, legacy_matches[0].code): return None,'LECTURER_IDENTITY_AMBIGUOUS'
        return legacy_matches[0], "CONFIRMED_ALIAS"
        
    KNOWN_ALIASES = {
        "thoan": "Phạm Đức Thoan",
        "pham duc thoan": "Phạm Đức Thoan",
        "cuong": "Lê Viết Cường",
        "le viet cuong": "Lê Viết Cường",
        "hang": "Trịnh Thị Minh Hằng",
        "trinh thi minh hang": "Trịnh Thị Minh Hằng",
        "nguyet": "Nguyễn Minh Nguyệt",
        "nguyen minh nguyet": "Nguyễn Minh Nguyệt",
        "x linh": "Nguyễn Xuân Linh",
        "xlinh": "Nguyễn Xuân Linh",
        "x_linh": "Nguyễn Xuân Linh",
        "nguyen xuan linh": "Nguyễn Xuân Linh",
        "mai hong": "Nguyễn Mai Hồng",
        "mai thi hong": "Nguyễn Mai Hồng",
        "nguyen mai hong": "Nguyễn Mai Hồng",
        "hai": "Nguyễn Thị Lệ Hải",
        "nguyen thi le hai": "Nguyễn Thị Lệ Hải",
        "huong giang": "Vũ Thị Hương Giang",
        "vu thi huong giang": "Vũ Thị Hương Giang",
        "nam": "Nguyễn Hải Nam",
        "nguyen hai nam": "Nguyễn Hải Nam",
        "ngan": "Vũ Thị Ngân",
        "vu thi ngan": "Vũ Thị Ngân",
        "lieu": "Trần Thị Liễu",
        "tran thi lieu": "Trần Thị Liễu",
        "trinh": "Bùi Khánh Trình",
        "bui khanh trinh": "Bùi Khánh Trình",
        "tuyet": "Lương Thị Tuyết",
        "luong thi tuyet": "Lương Thị Tuyết",
        "thuy": "Vũ Thị Thủy",
        "vu thi thuy": "Vũ Thị Thủy",
        "klinh": "Kiều Thị Thùy Linh",
        "k linh": "Kiều Thị Thùy Linh",
        "k_linh": "Kiều Thị Thùy Linh",
        "kieu thi thuy linh": "Kiều Thị Thùy Linh",
        "hung": "Ngô Quang Hùng",
        "ngo quang hung": "Ngô Quang Hùng",
        "khien": "Trần Văn Khiên",
        "tran van khien": "Trần Văn Khiên",
        "bang giang": "Nguyễn Bằng Giang",
        "nguyen bang giang": "Nguyễn Bằng Giang",
        "thuan": "Nguyễn Thị Thuần",
        "co thuan": "Nguyễn Thị Thuần",
        "co nguyen thi": "Nguyễn Thị Thuần",
        "co nguyen thi thuan": "Nguyễn Thị Thuần",
        "nguyen thi thuan": "Nguyễn Thị Thuần",
        "tuyen": "Nguyễn Văn Tuyên",
        "dang tuyen": "Nguyễn Văn Tuyên",
        "van tuyen": "Nguyễn Văn Tuyên",
        "nguyen dang tuyen": "Nguyễn Văn Tuyên",
        "nguyen van tuyen": "Nguyễn Văn Tuyên",
    }
    
    if normalized in KNOWN_ALIASES:
        given_matches = [l for l in all_lecturers if normalize_identity(l.canonical_name).split()[-1] == normalized]
        if len(given_matches) > 1:
            return None, 'LECTURER_IDENTITY_AMBIGUOUS'
        canonical_target = KNOWN_ALIASES[normalized]
        target_norm = normalize_identity(canonical_target)
        target_matches = [l for l in all_lecturers if normalize_identity(l.canonical_name) == target_norm]
        if len(target_matches) == 1:
            if code and target_matches[0].code and not _codes_compatible(code, target_matches[0].code):
                return None, 'LECTURER_IDENTITY_AMBIGUOUS'
            return target_matches[0], "CONFIGURED_ALIAS"

    return None, "LECTURER_IDENTITY_AMBIGUOUS" if matches or legacy_matches else "NEW_LECTURER_CANDIDATE"


def relink_source_identity(db, item, lecturer, semester_id):
    """Relink one source identity in one semester, preserving every source row."""
    from app.services.preference_validation import field_provenance
    key=source_identity_key(item.lecturer_alias,item.lecturer_code)
    # A blank identity is not shared evidence: link only this draft, never all
    # rows whose lecturer was absent from the input.
    anonymous=key=='name:'
    if anonymous: key=f'draft:{item.id}'
    affected=[draft for draft in db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id==semester_id))
              if (draft.id==item.id if anonymous else source_identity_key(draft.lecturer_alias,draft.lecturer_code)==key)]
    if any((d.applied_constraint_id or d.applied_seminar_id) and d.lecturer_id!=lecturer.id for d in affected):
        raise ValueError('Có nguyện vọng đã áp dụng; cần xử lý ràng buộc đang hoạt động trước khi đổi danh tính.')
    previous=item.lecturer_id
    changes=[]
    for draft in affected:
        changes.append({'draft_id':draft.id,'before':draft.lecturer_id,'after':lecturer.id})
        changed=draft.lecturer_id!=lecturer.id
        draft.lecturer_id=lecturer.id
        provenance=field_provenance(draft)
        provenance['lecturer_id']={'origin':'HUMAN_CONFIRMED','source_identity_key':key}
        draft.target={**(draft.target or {}),'identity_confirmed':True,'_provenance':provenance}
        if changed and draft.status!='REJECTED':
            draft.status='NEEDS_REVIEW';draft.needs_review=True
            draft.review_reason='Danh tính đã thay đổi; cần xác nhận lại nội dung.'
    db.add(LecturerIdentityAudit(source_lecturer_id=previous or lecturer.id,target_lecturer_id=lecturer.id,action='SOURCE_IDENTITY_LINK',snapshot={
        'semester_id':semester_id,'source_identity_key':key,'before':previous,'after':lecturer.id,'drafts':changes,
    }))
    # Obsolete identity diagnostics are replaced by the current linked state.
    from app.models.entities import ValidationIssue
    for issue in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id==semester_id,ValidationIssue.code=='LECTURER_IDENTITY_AMBIGUOUS')):
        if normalize_identity(issue.raw_value or '')==normalize_identity(item.lecturer_alias or ''):
            issue.severity='info';issue.code='LECTURER_IDENTITY_RESOLVED';issue.message='Danh tính nguồn đã được xác nhận.'
    db.flush()
    return [d.id for d in affected]


def confirm_alias(db: Session, lecturer: Lecturer, alias_text: str, replace: bool = False) -> LecturerAlias:
    normalized = normalize_identity(alias_text)
    if not normalized:
        raise ValueError("Alias không được để trống.")
    alias = db.scalar(select(LecturerAlias).where(LecturerAlias.normalized_alias == normalized))
    legacy_owners = [l for l in db.scalars(select(Lecturer)) if l.id != lecturer.id and any(
        normalize_identity(a) == normalized for a in (l.aliases or []))]
    if (alias and alias.lecturer_id != lecturer.id or legacy_owners) and not replace:
        raise ValueError("Alias đã liên kết với giảng viên khác; cần xác nhận đổi liên kết.")
    for owner in legacy_owners:
        owner.aliases = [a for a in owner.aliases if normalize_identity(a) != normalized]
    if alias is None:
        alias = LecturerAlias(lecturer_id=lecturer.id, alias_text=alias_text.strip(), normalized_alias=normalized, source="MANUAL", confirmed=True)
        db.add(alias)
    else:
        alias.lecturer_id = lecturer.id
        alias.confirmed = True
        alias.source = "MANUAL"
    lecturer.aliases = sorted(set([*(lecturer.aliases or []), alias_text.strip()]))
    return alias


def participation_reason(db: Session, lecturer: Lecturer, semester_id: int) -> str | None:
    if lecturer.status != "ACTIVE":
        return "LECTURER_INACTIVE"
    profile = db.scalar(select(LecturerSemesterProfile).where(
        LecturerSemesterProfile.lecturer_id == lecturer.id,
        LecturerSemesterProfile.semester_id == semester_id))
    if profile and profile.participation_status != "ACTIVE":
        return "LECTURER_NOT_PARTICIPATING"
    return None


def dependencies(db: Session, lecturer_id: int) -> dict:
    fields = [
        ("assignments", Assignment, Assignment.lecturer_id),
        ("classes", ClassSection, ClassSection.assigned_lecturer_id),
        ("constraints", Constraint, Constraint.lecturer_id),
        ("drafts", NormalizedPreferenceDraft, NormalizedPreferenceDraft.lecturer_id),
        ("capabilities", LecturerCourseCapability, LecturerCourseCapability.lecturer_id),
        ("participation", LecturerSemesterProfile, LecturerSemesterProfile.lecturer_id),
        ("aliases", LecturerAlias, LecturerAlias.lecturer_id),
        ("history", HistoricalEvidence, HistoricalEvidence.lecturer_id),
    ]
    result = {name: db.scalar(select(func.count()).select_from(model).where(field == lecturer_id)) for name, model, field in fields}
    result["seminars"] = sum(lecturer_id in (s.members or []) for s in db.scalars(select(Seminar)))
    lecturer = db.get(Lecturer, lecturer_id)
    result["legacy_aliases"] = len(lecturer.aliases or []) if lecturer else 0
    result["audit"] = db.scalar(select(func.count()).select_from(LecturerIdentityAudit).where(
        (LecturerIdentityAudit.source_lecturer_id == lecturer_id) | (LecturerIdentityAudit.target_lecturer_id == lecturer_id)))
    return result


def merge_lecturers(db: Session, source: Lecturer, target: Lecturer) -> dict:
    if source.id == target.id:
        raise ValueError("Giảng viên nguồn và đích phải khác nhau.")
    snapshot = {"source_name": source.canonical_name, "source_code": source.code, "target_name": target.canonical_name, "affected": dependencies(db, source.id)}
    # Conflicting confirmed capabilities/participation cannot be silently resolved.
    for model, key, fields in [
        (LecturerCourseCapability, "course_id", ("allowed", "confirmed")),
        (LecturerSemesterProfile, "semester_id", ("participation_status", "target_workload", "min_workload", "max_workload")),
    ]:
        for row in db.scalars(select(model).where(model.lecturer_id == source.id)).all():
            existing = db.scalar(select(model).where(model.lecturer_id == target.id, getattr(model, key) == getattr(row, key)))
            if existing:
                if any(getattr(existing, field) != getattr(row, field) for field in fields):
                    raise ValueError("Dữ liệu năng lực/tham gia học kỳ mâu thuẫn; cần chỉnh trước khi gộp.")
                db.delete(row)
            else:
                row.lecturer_id = target.id
    for model, field in [(LecturerAlias, "lecturer_id"), (NormalizedPreferenceDraft, "lecturer_id"), (Constraint, "lecturer_id"), (ClassSection, "assigned_lecturer_id")]:
        for row in db.scalars(select(model).where(getattr(model, field) == source.id)):
            setattr(row, field, target.id)
    for seminar in db.scalars(select(Seminar)):
        if source.id in (seminar.members or []):
            seminar.members = sorted({target.id if i == source.id else i for i in seminar.members})
    # Snapshot assignments and historical evidence keep the source id for auditability.
    target.aliases = sorted(set([*(target.aliases or []), *(source.aliases or [])]))
    source.aliases = []
    source.status = "INACTIVE"
    db.add(LecturerIdentityAudit(source_lecturer_id=source.id, target_lecturer_id=target.id, action="MERGE", snapshot=snapshot))
    db.flush()
    return snapshot
