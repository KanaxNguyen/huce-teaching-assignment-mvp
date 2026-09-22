"""Source identity, reviewed activation and quarantine. No assignment redesign."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.entities import (
    Assignment, ClassSection, ClassSession, Constraint, ImportBatch, Lecturer,
    NormalizedPreferenceDraft, OptimizationRun,
    Semester, Seminar, SourceVersion, ValidationIssue,
)
from app.storage import get_storage_backend

ROLES = {"CURRENT_SCHEDULE", "PREFERENCE", "HISTORICAL", "OUTPUT_TEMPLATE", "REFERENCE_MATRIX"}
BLOCKERS = {"MULTI_LECTURER_REVIEW", "SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT", "SOURCE_CHANGED_REVIEW_REQUIRED"}


class SourceError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.detail = {"code": code, "message": message, **details}


def source_payload(source, semester):
    return {"id": source.id, "source_type": source.source_type,
            "original_filename": source.original_filename, "content_hash": source.content_hash,
            "created_at": source.created_at.isoformat(), "provenance_status": source.provenance_status,
            "parent_version_id": source.parent_version_id, "parse_summary": source.parse_summary,
            "active": source.id in {semester.active_schedule_source_id, semester.active_preference_source_id}}


def register_source(db, path: Path, semester_id: int, role: str, *, parent_id=None, batch=None):
    if role not in ROLES or db.get(Semester, semester_id) is None:
        raise SourceError("SOURCE_ROLE_INVALID", "Chọn kỳ học và vai trò nguồn hợp lệ.")
    if parent_id:
        parent = db.get(SourceVersion, parent_id)
        if not parent or parent.semester_id != semester_id or parent.source_type != role:
            raise SourceError("SOURCE_PARENT_INVALID", "Nguồn cha phải cùng kỳ và cùng vai trò.")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = db.scalar(select(SourceVersion).where(SourceVersion.semester_id == semester_id,
        SourceVersion.source_type == role, SourceVersion.original_filename == path.name,
        SourceVersion.content_hash == content_hash))
    if existing:
        # Identical provenance reconciles reviewed drafts; a fresh upload event
        # still records that these exact bytes were seen again.
        db.add(ImportBatch(semester_id=semester_id, source_files=[path.name], summary={"event": "IDENTICAL_SOURCE_UPLOAD", "source_version_id": existing.id}))
        return existing
    if batch is None:
        batch = ImportBatch(semester_id=semester_id, source_files=[path.name], summary={"status": "STAGED"})
        db.add(batch); db.flush()
    ref = get_storage_backend().put(path, f"sources/{semester_id}/{uuid4().hex}/{role.lower()}/{path.name}")
    source = SourceVersion(semester_id=semester_id, import_batch_id=batch.id, source_type=role,
        original_filename=path.name, storage_ref=ref, content_hash=content_hash,
        provenance_status="VERIFIED", parent_version_id=parent_id, parse_summary={})
    db.add(source); db.flush()
    return source


def stage_source(db, path, semester_id, role, *, parent_id=None, batch=None):
    from app.services.importer import parse_schedule, _parse_preference_source, _summary
    # Parse before persisting; rejected rows are retained in candidate diagnostics.
    if role == "CURRENT_SCHEDULE":
        parsed = parse_schedule(path)
        summary = {**_summary(parsed), "issues": [vars(i) for i in parsed.issues]}
    elif role == "PREFERENCE":
        parsed = _parse_preference_source(path, db.get(Semester, semester_id))
        summary = {"format": parsed.format, "drafts": len(parsed.drafts), "seminars": len(parsed.seminars),
                   "invalid_rows": parsed.invalid_rows, "warnings": parsed.warnings}
    else:
        summary = {"status": "REFERENCE_ONLY"}
    source = register_source(db, path, semester_id, role, parent_id=parent_id, batch=batch)
    if not source.parse_summary:
        source.parse_summary = summary
    db.flush()
    return source


def current_run_predicate(semester):
    return (OptimizationRun.semester_id == semester.id) & (OptimizationRun.source_revision == semester.source_revision) & (
        OptimizationRun.schedule_source_id == semester.active_schedule_source_id) & (
        OptimizationRun.preference_source_id == semester.active_preference_source_id)


def latest_current_run(db, semester_id):
    semester = db.get(Semester, semester_id)
    return db.scalar(select(OptimizationRun).where(current_run_predicate(semester)).order_by(OptimizationRun.id.desc()))


def run_context(semester):
    return {"schedule_source_id": semester.active_schedule_source_id,
            "preference_source_id": semester.active_preference_source_id, "source_revision": semester.source_revision}


def active_issues(db, semester_id):
    return db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == semester_id,
        ValidationIssue.resolution_status.in_(["OPEN", "DEFERRED_SPECIAL_CASE"]))).all()


def source_blockers(db, semester_id):
    semester = db.get(Semester, semester_id)
    result = [{"code": i.code, "issue_id": i.id, "message": i.message, "details": i.details}
              for i in active_issues(db, semester_id) if i.code in BLOCKERS]
    # Legacy datasets stay inspectable but require explicit verified activation.
    if semester.active_schedule_source_id is None and db.scalar(select(SourceVersion.id).where(SourceVersion.semester_id == semester_id)) is not None:
        result.append({"code": "ACTIVE_SCHEDULE_REQUIRED", "message": "Cần xác nhận nguồn lịch đang sử dụng."})
    return result


def _record(group, meeting):
    return {"course": group.course.code, "class_code": group.class_code, "day": meeting.weekday,
            "period": [meeting.start_period, meeting.end_period], "room": meeting.room,
            "week_mask": meeting.active_weeks,
            "date_range": [meeting.start_date.isoformat() if meeting.start_date else None,
                           meeting.end_date.isoformat() if meeting.end_date else None],
            "source_rows": meeting.source_rows or [meeting.source_row]}


def _candidate_records(parsed):
    return [{"course": g.course_code, "class_code": g.class_code, "day": m.weekday,
             "period": [m.start_period, m.end_period], "room": m.room, "week_mask": m.active_weeks,
             "date_range": [m.start_date.isoformat() if m.start_date else None, m.end_date.isoformat() if m.end_date else None],
             "source_rows": m.source_rows or [m.source_row]}
            for g in parsed.classes for m in g.sessions]


def meeting_diff(before, after):
    """Exact matches first; conservative unique correspondence only, never row-index guessing."""
    fields = ("course", "class_code", "day", "period", "room", "week_mask", "date_range")
    def key(row, names=fields): return json.dumps([row[k] for k in names], sort_keys=True)
    old, new = list(before), list(after)
    result = []
    for left in before:
        match = next((right for right in new if key(left) == key(right)), None)
        if match is not None:
            old.remove(left); new.remove(match)
            result.append({"status": "UNCHANGED", "before": left, "after": match, "changed_fields": []})
    # Single-meeting group changes and a unique one-field correction can be paired.
    for left in list(old):
        matches = [r for r in new if (r['course'], r['class_code']) == (left['course'], left['class_code'])]
        if len(matches) != 1 or sum((r['course'], r['class_code']) == (left['course'], left['class_code']) for r in old) != 1:
            matches = [r for r in new if sum(left[f] != r[f] for f in fields) == 1]
            if len(matches) != 1 or sum(sum(l[f] != matches[0][f] for f in fields) == 1 for l in old) != 1:
                continue
        right = matches[0]
        old.remove(left); new.remove(right)
        result.append({"status": "CHANGED", "before": left, "after": right,
                       "changed_fields": [f for f in fields if left[f] != right[f]]})
    result.extend({"status": "REMOVED", "before": r, "after": None, "changed_fields": []} for r in old)
    result.extend({"status": "ADDED", "before": None, "after": r, "changed_fields": []} for r in new)
    return {"counts": {kind: sum(r['status'] == kind for r in result) for kind in ["UNCHANGED", "ADDED", "REMOVED", "CHANGED"]}, "meetings": result}


def require_source(db, semester_id, source_id, role=None):
    source = db.get(SourceVersion, source_id)
    if not source or source.semester_id != semester_id:
        raise SourceError("SOURCE_SEMESTER_MISMATCH", "Nguồn không thuộc kỳ học đang chọn.")
    if role and source.source_type != role:
        raise SourceError("SOURCE_ROLE_MISMATCH", "Vai trò nguồn không được phép kích hoạt cho loại dữ liệu này.")
    return source


def preview_activation(db, semester_id, source_id, role):
    from app.services.importer import parse_schedule, _parse_preference_source
    source = require_source(db, semester_id, source_id, role)
    if role not in {"CURRENT_SCHEDULE", "PREFERENCE"}:
        raise SourceError("SOURCE_ROLE_MISMATCH", "Nguồn tham chiếu không thể trở thành lịch/nguyện vọng ngầm định.")
    semester = db.get(Semester, semester_id)
    with get_storage_backend().materialize(source.storage_ref) as path:
        if hashlib.sha256(path.read_bytes()).hexdigest() != source.content_hash:
            raise SourceError("SOURCE_HASH_MISMATCH", "Nội dung nguồn lưu trữ không khớp hash.")
        groups = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id == semester_id)).all()
        before = [_record(g, m) for g in groups for m in g.sessions]
        if role == "CURRENT_SCHEDULE":
            parsed = parse_schedule(path)
            diff = meeting_diff(before, _candidate_records(parsed))
            diagnostics = [vars(i) for i in parsed.issues]
            can_activate = bool(parsed.classes) and parsed.rows_rejected == 0 and not any(i.severity == 'error' and i.code != 'MULTI_LECTURER_REVIEW' for i in parsed.issues)
        else:
            parsed = _parse_preference_source(path, semester)
            diff = {"drafts": len(parsed.drafts), "seminars": len(parsed.seminars), "previous_rules_require_review": True}
            diagnostics = parsed.warnings
            can_activate = bool(parsed.drafts or parsed.seminars)
    base = {"source": source.id, "hash": source.content_hash, "role": role,
            "revision": semester.source_revision, "active_schedule": semester.active_schedule_source_id,
            "active_preference": semester.active_preference_source_id, "meetings": before, "diff": diff}
    token = hashlib.sha256(json.dumps(base, sort_keys=True, default=str).encode()).hexdigest()
    return {"source_id": source.id, "source_type": role, "filename": source.original_filename,
            "preview_token": token, "base_revision": semester.source_revision, "can_activate": can_activate,
            "diff": diff, "diagnostics": diagnostics,
            "consequences": ["Thay đổi nguồn làm các run cũ trở thành lịch sử.", "Tham chiếu lớp cũ cần xác nhận lại; phân công, khóa và ghép lớp cũ không được chuyển ngầm."]}


def archive_schedule(db, semester_id):
    """Freeze old run output before deleting materialized meetings. Runs survive."""
    runs = db.scalars(select(OptimizationRun).where(OptimizationRun.semester_id == semester_id)).all()
    for run in runs:
        assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
        if assignments:
            run.summary = {**run.summary, "archived_assignments": [
                {"class_id": a.class_id, "lecturer_id": a.lecturer_id, "lecturer": a.lecturer.canonical_name,
                 "locked": a.locked, "source": a.source,
                 "meetings": [_record(a.class_section, m) for m in a.class_section.sessions]} for a in assignments]}
    # Current manual/imported decisions also survive in an audit batch.
    groups = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id)).all()
    if groups:
        db.add(ImportBatch(semester_id=semester_id, source_files=[], summary={"event": "SOURCE_REPLACEMENT_ARCHIVE",
            "groups": [{"id": g.id, "source_version_id": g.source_version_id, "class_code": g.class_code,
                        "lecturer_id": g.assigned_lecturer_id, "locked": g.locked_assignment,
                        "assignment_source": g.assignment_source, "merge_status": g.merge_status,
                        "merged_group_id": g.merged_group_id, "meetings": [_record(g,m) for m in g.sessions]} for g in groups]}))
    db.flush()


def invalidate_sources(db, semester, *, schedule_change=False, preference_change=False):
    changed_drafts = []
    if preference_change:
        for issue in active_issues(db, semester.id):
            if issue.source_version_id == semester.active_preference_source_id:
                issue.resolution_status = 'SUPERSEDED'
    for draft in db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id == semester.id)):
        class_link = any(k in (draft.target or {}) for k in ('class_id', 'class_ids', 'teaching_group_id', 'meeting_id'))
        if (schedule_change and class_link) or (preference_change and (draft.source_version_id is not None or draft.source_file != "MANUAL")):
            draft.target = {**draft.target, "_prior_review": {"status": draft.status, "needs_review": draft.needs_review,
                "review_reason": draft.review_reason, "applied_constraint_id": draft.applied_constraint_id,
                "applied_seminar_id": draft.applied_seminar_id}}
            if draft.status != "REJECTED":
                draft.status = "NEEDS_REVIEW"; draft.needs_review = True
                draft.review_reason = "SOURCE_CHANGED_REVIEW_REQUIRED"
            draft.target = {**draft.target, "_stale_source_reference": True}
            changed_drafts.append(draft.id)
            if draft.applied_constraint_id:
                constraint = db.get(Constraint, draft.applied_constraint_id)
                if constraint: constraint.active = False
                draft.applied_constraint_id = None
            if draft.applied_seminar_id:
                seminar = db.get(Seminar, draft.applied_seminar_id)
                if seminar:
                    # Keep historical draft metadata; remove obsolete active event.
                    draft.target = {**draft.target, "_archived_seminar": {"name": seminar.name, "members": seminar.members, "alternatives": seminar.alternatives}}
                    draft.applied_seminar_id = None
                    db.flush(); db.delete(seminar)
    for rule in db.scalars(select(Constraint).where(Constraint.semester_id == semester.id)):
        linked = any(k in (rule.target or {}) for k in ('class_id', 'class_ids', 'teaching_group_id', 'meeting_id'))
        if (schedule_change and linked) or (preference_change and rule.source_version_id is not None):
            rule.active = False; rule.confirmed = False
            rule.target = {**rule.target, "_stale_source_reference": True}
    db.flush()
    return changed_drafts


def activate_source(db, semester_id, source_id, role, *, confirmed, preview_token):
    from app.services.importer import _import_files_impl
    if confirmed is not True:
        raise SourceError("SOURCE_ACTIVATION_CONFIRMATION_REQUIRED", "Cần xem đối chiếu và xác nhận kích hoạt.")
    try:
        preview = preview_activation(db, semester_id, source_id, role)
        if not preview['can_activate']:
            raise SourceError("SOURCE_PARSE_REVIEW_REQUIRED", "Nguồn có dòng bị loại hoặc không có dữ liệu; cần sửa nguồn trước khi kích hoạt.")
        if not preview_token or preview_token != preview['preview_token']:
            raise SourceError("SOURCE_PREVIEW_STALE", "Dữ liệu đã thay đổi; hãy xem đối chiếu mới trước khi xác nhận.")
        semester = db.get(Semester, semester_id)
        source = require_source(db, semester_id, source_id, role)
        field = 'active_schedule_source_id' if role == 'CURRENT_SCHEDULE' else 'active_preference_source_id'
        if getattr(semester, field) == source.id:
            return {"active": True, "unchanged": True}
        revision = semester.source_revision
        cas = db.execute(update(Semester).where(Semester.id == semester_id, Semester.source_revision == revision).values(source_revision=revision + 1).execution_options(synchronize_session=False))
        if cas.rowcount != 1:
            raise SourceError("SOURCE_PREVIEW_STALE", "Nguồn đang được thay đổi ở phiên khác.")
        changed = invalidate_sources(db, semester, schedule_change=role == 'CURRENT_SCHEDULE', preference_change=role == 'PREFERENCE')
        with get_storage_backend().materialize(source.storage_ref) as path:
            result = _import_files_impl(db, [path], semester_id=semester_id,
                schedule_paths=[path] if role == 'CURRENT_SCHEDULE' else [],
                preference_paths=[path] if role == 'PREFERENCE' else [],
                schedule_source=source if role == 'CURRENT_SCHEDULE' else None,
                preference_source=source if role == 'PREFERENCE' else None,
                replace_schedule=role == 'CURRENT_SCHEDULE', commit=False)
        setattr(semester, field, source.id); semester.source_revision = revision + 1
        # Show a durable review record for stale targets; it can be dismissed only
        # after obsolete rules are acknowledged, never silently reactivated.
        if changed or db.scalar(select(Constraint.id).where(Constraint.semester_id == semester_id, Constraint.active.is_(False), Constraint.confirmed.is_(False))):
            db.add(ValidationIssue(semester_id=semester_id, source_version_id=source.id,
                severity='error', code='SOURCE_CHANGED_REVIEW_REQUIRED', message='Nguồn đã thay đổi; rà soát và bỏ hoặc thay thế các tham chiếu cũ.',
                details={'draft_ids': changed, 'source_version_id': source.id}, resolution_status='OPEN'))
        db.add(ImportBatch(semester_id=semester_id, source_files=[source.original_filename], summary={
            'event': 'SOURCE_ACTIVATED', 'source_version_id': source.id, 'source_revision': revision + 1,
            'preview_token': preview_token, 'diff': preview['diff'], 'confirmed': True}))
        db.commit()
        return {"active": True, "source_id": source.id, "source_revision": revision + 1, "import": result}
    except Exception:
        db.rollback()
        raise


def resolve_issue(db, semester_id, issue_id, *, action, lecturer_id=None, note='', actor=''):
    issue = db.get(ValidationIssue, issue_id)
    if not issue or issue.semester_id != semester_id or issue.resolution_status == 'SUPERSEDED':
        raise SourceError('SOURCE_REVIEW_NOT_FOUND', 'Vấn đề không thuộc nguồn hiện hành.')
    if not note.strip() or not actor.strip():
        raise SourceError('SOURCE_REVIEW_AUDIT_REQUIRED', 'Nhập người xác nhận và lý do xử lý.')
    semester = db.get(Semester, semester_id)
    if issue.code in {'MULTI_LECTURER_REVIEW', 'SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT'}:
        group = db.get(ClassSection, issue.details.get('class_id'))
        if not group or group.source_version_id != semester.active_schedule_source_id:
            raise SourceError('SOURCE_PREVIEW_STALE', 'Nhóm lớp không thuộc nguồn đang hoạt động.')
        if action == 'DEFER_SPECIAL':
            group.assigned_lecturer_id = None; group.locked_assignment = False
            issue.code = 'SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT'
            issue.resolution_status = 'DEFERRED_SPECIAL_CASE'
            issue.message = f'{group.class_code}: tách/đồng giảng cần hỗ trợ AssignmentSegment; chưa được solve.'
        elif action in {'NORMALIZE_SINGLE', 'CORRECT_INTERPRETATION'}:
            lecturer = db.get(Lecturer, lecturer_id) if lecturer_id else None
            if not lecturer:
                raise SourceError('LECTURER_REQUIRED', 'Chọn giảng viên chuẩn cho toàn bộ nhóm.')
            from app.services.lecturer_master import participation_reason
            if participation_reason(db, lecturer, semester_id):
                raise SourceError('LECTURER_NOT_PARTICIPATING', 'Giảng viên không tham gia kỳ học.')
            # Explicit human confirmation supplies the association; capability is
            # still separately governed by the existing capability workflow.
            group.assigned_lecturer_id = lecturer.id; group.assignment_source = 'MANUAL'; group.locked_assignment = False
            issue.resolution_status = 'RESOLVED'; issue.severity = 'info'
        else:
            raise SourceError('SOURCE_REVIEW_ACTION_INVALID', 'Chọn chuẩn hóa một giảng viên hoặc hoãn trường hợp đặc biệt.')
    elif issue.code == 'SOURCE_CHANGED_REVIEW_REQUIRED' and action == 'ACKNOWLEDGE_STALE':
        issue.resolution_status = 'RESOLVED'; issue.severity = 'info'
    else:
        raise SourceError('SOURCE_REVIEW_ACTION_INVALID', 'Không hỗ trợ hành động xử lý này.')
    history = list((issue.details or {}).get('audit', []))
    history.append({'action': action, 'lecturer_id': lecturer_id, 'note': note.strip(), 'actor': actor.strip(), 'at': datetime.now(timezone.utc).isoformat()})
    issue.details = {**issue.details, 'resolution_status': issue.resolution_status, 'audit': history}
    db.commit()
    return {'id': issue.id, 'code': issue.code, 'resolution_status': issue.resolution_status}
