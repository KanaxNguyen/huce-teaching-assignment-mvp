from __future__ import annotations

from collections import defaultdict
import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask
from xlrd.biffh import XLRDError

from app.core.config import settings
from app.db.session import get_db
from app.exporters.excel import export_latest, export_matrix
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    HistoricalEvidence,
    Lecturer,
    LecturerCourseCapability,
    NormalizedPreferenceDraft,
    OptimizationRun,
    OutputTemplateProfile,
    Semester,
    SourceVersion,
    ImportBatch,
    Seminar,
    ValidationIssue,
)
from app.optimization.solver import solve
from app.optimization.occurrences import are_classes_mergeable
from app.services.historical_learning import learn_from_template_profile
from app.parsers.preferences import describe_preference
from app.schemas.api import (
    AliasResolution,
    CapabilityBulkConfirmRequest,
    CapabilityUpdateRequest,
    ConstraintCreate,
    ConstraintUpdate,
    DepartmentCreate,
    DepartmentPolicyUpdate,
    ImportResponse,
    MergedDecision,
    MergeClassesRequest,
    UnmergeClassesRequest,
    ManualPreferenceDraftCreate,
    OptimizationRequest,
    PreferenceDraftApply,
    PreferenceDraftUpdate,
    SemesterCreate,
    SeminarCreate,
    TemplateMappingUpdate,
)
from app.services.importer import dashboard
from app.services.source_authority import (SourceError, stage_source, register_source, source_payload, latest_current_run, current_run_predicate, source_blockers, active_issues)
from app.services.manual_assignment import apply_manual_assignment, check_assignment_change
from app.services.template_detector import detect_output_template
from app.services.lecturer_master import confirm_alias
from app.storage import get_storage_backend

router = APIRouter(prefix="/api/v1")

def _semester_id(db: Session, requested: int | None) -> int:
    semester = db.get(Semester, requested) if requested is not None else db.scalar(
        select(Semester).where(Semester.is_active.is_(True)).order_by(Semester.id.desc())
    )
    if not semester:
        raise HTTPException(422, "Cần chọn kỳ học.")
    return semester.id


WORKBOOK_ERRORS = (BadZipFile, InvalidFileException, XLRDError, OSError)
STORAGE_WORKBOOK_ERRORS = (FileNotFoundError, ValueError) + WORKBOOK_ERRORS


def _copy_upload_limited(item: UploadFile, path: Path) -> None:
    total = 0
    with path.open("xb") as handle:
        while chunk := item.file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise HTTPException(413, "File vượt quá dung lượng cho phép.")
            handle.write(chunk)


@contextmanager
def _temporary_typed_upload(item: UploadFile):
    raw_name = Path((item.filename or "upload").replace("\\", "/")).name
    raw_suffix = Path(raw_name).suffix
    safe_name = f"{Path(raw_name).stem[:160]}{raw_suffix}" or "upload"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise HTTPException(415, f"Định dạng không hỗ trợ: {suffix}")
    with tempfile.TemporaryDirectory(prefix="huce-upload-") as directory:
        # The directory is unique, while the basename is retained because it
        # is import provenance used by the existing exporter row matching.
        path = Path(directory) / safe_name
        _copy_upload_limited(item, path)
        yield path


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "HUCE Teaching Assignment API"}


@router.get("/semesters")
def get_semesters(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "department_id": item.department_id,
            "department_name": item.department_name,
            "start_date": item.start_date,
            "end_date": item.end_date,
            "head_name": item.head_name,
            "status": item.status,
            "is_active": item.is_active,
        }
        for item in db.scalars(select(Semester).order_by(Semester.id.desc())).all()
    ]


@router.post("/semesters")
def create_semester(payload: SemesterCreate, db: Session = Depends(get_db)) -> dict:
    try:
        start_date = date.fromisoformat(payload.start_date)
        end_date = date.fromisoformat(payload.end_date)
    except ValueError as error:
        raise HTTPException(422, "Ngày bắt đầu hoặc kết thúc không hợp lệ.") from error
    if end_date < start_date:
        raise HTTPException(422, "Ngày kết thúc phải sau ngày bắt đầu.")
    for semester in db.scalars(select(Semester).where(Semester.is_active.is_(True))).all():
        semester.is_active = False

    dept_id = payload.department_id
    if not dept_id and payload.department_name:
        from app.core.department_policies import resolve_or_create_department
        dept = resolve_or_create_department(db, payload.department_name)
        dept_id = dept.id

    item = Semester(
        name=payload.name.strip(),
        department_name=payload.department_name.strip(),
        department_id=dept_id,
        start_date=start_date,
        end_date=end_date,
        head_name=payload.head_name.strip(),
        status="draft",
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "created": True}


@router.post("/templates/detect")
def detect_template(
    template_file: UploadFile = File(...),
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    sid = _semester_id(db, semester_id)
    try:
        with _temporary_typed_upload(template_file) as path:
            result = detect_output_template(path)
            reference = get_storage_backend().put(
                path, f"templates/{sid}/{uuid4().hex}/{path.name}"
            )
            source_version = register_source(db, path, sid, "REFERENCE_MATRIX" if result.get("layout") == "matrix" else "OUTPUT_TEMPLATE")
            profile = OutputTemplateProfile(
                source_version_id=source_version.id,
                semester_id=sid,
                source_file=reference,
                source_sheet=result["source_sheet"],
                header_row=result["header_row"],
                mappings=result["mappings"],
                missing_fields=result["missing_fields"],
                preview=result["preview"],
                profile_type="DEPARTMENT_MATRIX" if result.get("layout") == "matrix" else "DETAILED_ASSIGNMENT",
            )
            db.add(profile)
            db.commit()
            result["profile_id"] = profile.id
            try:
                evidence_summary = learn_from_template_profile(db, profile, path)
                result["historical_learning"] = evidence_summary
                result["lecturer_identity_summary"] = {
                    "total": evidence_summary.get("total_lecturers", result.get("historical_summary", {}).get("lecturers_count", 0)),
                    "with_code": evidence_summary.get("with_code", result.get("historical_summary", {}).get("lecturers_with_code", 0)),
                    "matched_master": evidence_summary.get("matched_master", evidence_summary.get("known_lecturers", 0)),
                    "need_review": evidence_summary.get("need_review", evidence_summary.get("new_candidates", 0)),
                    "new_candidates": evidence_summary.get("new_candidates", 0),
                }
            except Exception:
                db.rollback()
                result["historical_learning"] = {"status": "NEEDS_REVIEW", "message": "Nhận diện mẫu thành công nhưng chưa trích xuất được lịch sử; cần rà soát."}
            return result
    except WORKBOOK_ERRORS as error:
        raise HTTPException(422, "Không thể đọc workbook mẫu.") from error


@router.get("/templates/latest")
def get_latest_template(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict | None:
    try:
        sid = _semester_id(db, semester_id)
    except HTTPException:
        return None
    profile = db.scalars(
        select(OutputTemplateProfile).where(OutputTemplateProfile.semester_id == sid).order_by(OutputTemplateProfile.id.desc()).limit(1)
    ).first()
    if not profile:
        return None
    try:
        with get_storage_backend().materialize(profile.source_file) as source_path:
            result = detect_output_template(source_path)
            # User override preservation: human mappings > automatic redetection
            if profile.mappings:
                for field, mapping in profile.mappings.items():
                    result["mappings"][field] = mapping
                from app.services.template_detector import REQUIRED_FIELDS
                result["missing_fields"] = [f for f in REQUIRED_FIELDS if f not in result["mappings"]]
                result["ready"] = len(result["missing_fields"]) == 0
    except STORAGE_WORKBOOK_ERRORS:
        result = {
            "source_file": profile.source_file,
            "source_sheet": profile.source_sheet,
            "layout": "table",
            "layout_label": "Bảng dữ liệu theo cột",
            "header_row": profile.header_row,
            "mappings": profile.mappings,
            "missing_fields": profile.missing_fields,
            "available_columns": [],
            "weekday_columns": [],
            "preview": profile.preview,
            "ready": not profile.missing_fields,
        }
    result["profile_id"] = profile.id
    evidence_rows = db.scalars(select(HistoricalEvidence).where(HistoricalEvidence.profile_id == profile.id)).all()
    if evidence_rows:
        unique_lecturers = {e.source_text for e in evidence_rows}
        with_code = {e.source_text for e in evidence_rows if e.lecturer_code}
        matched = {e.lecturer_id for e in evidence_rows if e.lecturer_id is not None}
        new_cands = {e.source_text for e in evidence_rows if e.status == "NEW_LECTURER_CANDIDATE"}
        result["lecturer_identity_summary"] = {
            "total": len(unique_lecturers),
            "with_code": len(with_code),
            "matched_master": len(matched),
            "need_review": len(new_cands),
            "new_candidates": len(new_cands),
        }
    return result


@router.patch("/templates/{profile_id}")
def update_template_mapping(
    profile_id: int,
    payload: TemplateMappingUpdate,
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.get(OutputTemplateProfile, profile_id)
    if not profile or profile.semester_id != _semester_id(db, semester_id):
        raise HTTPException(404, "Không tìm thấy mẫu đầu ra.")
    profile.mappings = payload.mappings
    profile.missing_fields = payload.missing_fields
    db.commit()
    return {"id": profile.id, "updated": True, "ready": not profile.missing_fields}


@router.post("/imports/local")
def import_local(semester_id: int | None = Query(None), db: Session = Depends(get_db)):
    raise HTTPException(422, {"code": "EXPLICIT_SOURCE_ROLE_REQUIRED", "message": "Tải từng nguồn với vai trò rõ ràng; xem đối chiếu rồi kích hoạt."})


@router.post("/imports/upload")
def upload(files: list[UploadFile] = File(...), source_type: str = Query(...), semester_id: int | None = Query(None), db: Session = Depends(get_db)):
    sid = _semester_id(db, semester_id)
    try:
        with ExitStack() as stack:
            paths = [stack.enter_context(_temporary_typed_upload(item)) for item in files]
            sources = [stage_source(db, path, sid, source_type) for path in paths]
            db.commit()
            return {"status": "STAGED", "sources": [source_payload(s, db.get(Semester, sid)) for s in sources]}
    except SourceError as error:
        db.rollback(); raise HTTPException(422, error.detail) from error
    except (ValueError, *WORKBOOK_ERRORS) as error:
        db.rollback(); raise HTTPException(422, "Không thể đọc nguồn đã tải lên.") from error


@router.post("/imports/upload-pair")
def upload_pair(schedule_file: UploadFile = File(...), preference_file: UploadFile = File(...),
                semester_id: int | None = Query(None), db: Session = Depends(get_db)):
    sid = _semester_id(db, semester_id)
    try:
        with ExitStack() as stack:
            schedule_path = stack.enter_context(_temporary_typed_upload(schedule_file))
            preference_path = stack.enter_context(_temporary_typed_upload(preference_file))
            batch = ImportBatch(semester_id=sid, source_files=[schedule_path.name, preference_path.name], summary={"status": "STAGED"})
            db.add(batch); db.flush()
            sources = [stage_source(db, schedule_path, sid, "CURRENT_SCHEDULE", batch=batch),
                       stage_source(db, preference_path, sid, "PREFERENCE", batch=batch)]
            db.commit()
            return {"status": "STAGED", "sources": [source_payload(s, db.get(Semester, sid)) for s in sources]}
    except SourceError as error:
        db.rollback(); raise HTTPException(422, error.detail) from error
    except (ValueError, *WORKBOOK_ERRORS) as error:
        db.rollback(); raise HTTPException(422, "Không thể đọc workbook đã tải lên.") from error


from app.services.preference_validation import validate_preference_draft, transition_status, field_provenance, SEMANTIC_FIELDS, values as draft_values


def _draft_payload(item: NormalizedPreferenceDraft) -> dict:
    interpreted = item.constraint_type == "RAW_NOTE" and item.status == "INTERPRETED"
    validation = ({"is_confirmable": False, "validation_errors": [], "validation_warnings": []}
                  if interpreted else validate_preference_draft(item))
    interpreted_rules = (item.target or {}).get("interpreted_rules") or []
    return {
        "id": item.id, "batch_id": item.import_batch_id, "draft_kind": item.draft_kind,
        "lecturer_id": item.lecturer_id, "lecturer": item.lecturer.canonical_name if item.lecturer else None,
        "lecturer_code": item.lecturer_code, "lecturer_alias": item.lecturer_alias,
        "context_type": item.context_type or "TEACHING", "context_confidence": item.context_confidence,
        "context_confirmed": item.context_confirmed,
        "constraint_type": item.constraint_type, "day_scope": item.day_scope,
        "source_version_id": item.source_version_id,
        "periods": item.periods, "start_date": item.start_date, "end_date": item.end_date,
        "hardness": item.hardness, "weight": item.weight, "numeric_value": item.numeric_value,
        "target": item.target, "participant_codes": item.participant_codes, "seminar_link": item.seminar_link,
        "normalized_text": ("Đã diễn giải thành: " + "; ".join(
            describe_preference(rule.get("constraint_type", ""), rule.get("target") or {})
            for rule in interpreted_rules
        )) if interpreted_rules else ("Đã lưu nguyên văn; không tạo ràng buộc solver." if interpreted else
            (describe_preference(item.constraint_type,item.target or {}) if item.day_scope or item.target.get('start_date') else 'Chưa xác định đủ phạm vi; cần rà soát.')),
        "source_file": item.source_file, "source_sheet": item.source_sheet,
        "source_row": item.source_row, "source_cell": item.source_cell, "raw_text": item.raw_text,
        "confidence": item.confidence, "needs_review": item.needs_review,
        "review_reason": item.review_reason, "status": item.status,
        "rejected_at": item.rejected_at.isoformat() if item.rejected_at else None,
        "rejected_reason": item.rejected_reason,
        "applied_constraint_id": item.applied_constraint_id, "applied_seminar_id": item.applied_seminar_id,
        **validation,
        "field_provenance": field_provenance(item),
    }


@router.get("/preference-drafts")
def get_preference_drafts(semester_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    _semester_id(db, semester_id)
    items = db.scalars(
        select(NormalizedPreferenceDraft)
        .where(NormalizedPreferenceDraft.semester_id == semester_id, or_(NormalizedPreferenceDraft.source_version_id.is_(None), NormalizedPreferenceDraft.source_version_id == db.get(Semester, semester_id).active_preference_source_id))
        .options(selectinload(NormalizedPreferenceDraft.lecturer))
        .order_by(NormalizedPreferenceDraft.lecturer_alias, NormalizedPreferenceDraft.source_row, NormalizedPreferenceDraft.id)
    ).all()
    return [_draft_payload(item) for item in items]


def _manual_draft_values(part, lecturer: Lecturer, semester_id: int) -> dict:
    if part.day_scope and part.day_scope not in {"T2", "T3", "T4", "T5", "T6", "T7", "CN", "ALL_WEEKDAYS", "ALL_DAYS"}:
        raise HTTPException(422, "Phạm vi ngày không hợp lệ.")
    if any(period < 1 or period > 15 for period in part.periods):
        raise HTTPException(422, "Tiết phải nằm trong 1–15.")
    teaching_types = {"UNAVAILABLE", "AVOID_PERIOD", "PREFERRED_PERIOD", "PREFERRED_DAYS", "AVOID_DAYS", "PREFER_LOW_WORKLOAD", "PREFER_COMPACT_SCHEDULE", "PREFER_CONSECUTIVE_PERIODS", "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "RAW_NOTE"}
    seminar_types = {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}
    allowed = teaching_types if part.context_type == "TEACHING" else seminar_types
    if part.constraint_type not in allowed:
        raise HTTPException(422, "Loại rule không phù hợp ngữ cảnh.")
    needs_review = part.constraint_type in {"RAW_NOTE", "SEMINAR_NOTE", "PREFER_CONSECUTIVE_PERIODS", "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT"}
    if part.context_type == "SEMINAR" and part.constraint_type == "SEMINAR_COMMITMENT" and (not part.day_scope or not part.periods):
        needs_review = True
    try:
        start_date = date.fromisoformat(part.start_date) if part.start_date else None
        end_date = date.fromisoformat(part.end_date) if part.end_date else None
    except ValueError as error:
        raise HTTPException(422, "Khoảng ngày không hợp lệ.") from error
    if start_date and end_date and end_date < start_date:
        raise HTTPException(422, "Ngày kết thúc phải không trước ngày bắt đầu.")
    target = {"day_scope": part.day_scope, "periods": part.periods,
              "context_type": part.context_type, "seminar_link": part.seminar_link}
    if part.day_scope in {"T2", "T3", "T4", "T5", "T6", "T7"}:
        target["weekday"] = int(part.day_scope[1:])
    elif part.day_scope == "CN":
        target["weekday"] = 8
    elif part.day_scope in {"ALL_WEEKDAYS", "ALL_DAYS"}:
        weekdays = range(2, 7) if part.day_scope == "ALL_WEEKDAYS" else range(2, 9)
        target["slots"] = [{"weekday": weekday, "periods": part.periods} for weekday in weekdays]
    if start_date: target["start_date"] = start_date.isoformat()
    if end_date: target["end_date"] = end_date.isoformat()
    if part.numeric_value is not None:
        target.update({"value": part.numeric_value, "max": part.numeric_value})
        if part.constraint_type == "MIN_CLASSES":
            target.pop("max", None); target["min"] = part.numeric_value
    return {
        "semester_id": semester_id, "lecturer_id": lecturer.id, "lecturer_code": lecturer.code,
        "lecturer_alias": lecturer.canonical_name, "draft_kind": "CONSTRAINT",
        "context_type": part.context_type, "context_confidence": "HIGH", "context_confirmed": True,
        "constraint_type": part.constraint_type, "day_scope": part.day_scope, "periods": part.periods,
        "start_date": start_date, "end_date": end_date, "hardness": part.hardness,
        "weight": part.weight, "numeric_value": part.numeric_value, "target": target,
        "seminar_link": part.seminar_link, "source_file": "MANUAL", "source_sheet": "Step04",
        "source_row": 0, "source_cell": "MANUAL", "raw_text": part.note,
        "confidence": "HIGH", "needs_review": needs_review,
        "review_reason": "Cần bổ sung scheduling semantics cụ thể." if needs_review else None,
        "status": "NEEDS_REVIEW" if needs_review else part.status,
    }


@router.post('/preference-drafts/validate')
def validate_new_draft(payload: dict, semester_id: int = Query(...), db: Session = Depends(get_db)):
    _semester_id(db,semester_id)
    parts=payload.get('parts') if payload.get('context_type')=='MIXED' else [payload]
    if not isinstance(parts,list) or not parts:
        raise HTTPException(422,'Cần có các phần nguyện vọng để kiểm tra.')
    results=[validate_preference_draft({**part,'lecturer_id':payload.get('lecturer_id'),'semester_id':semester_id},db) for part in parts if isinstance(part,dict)]
    if len(results)!=len(parts): raise HTTPException(422,'Phần nguyện vọng không hợp lệ.')
    errors=[error for result in results for error in result['validation_errors']]
    return {'is_confirmable':not errors,'validation_errors':errors,'validation_warnings':[]}


@router.post("/preference-drafts")
def create_manual_preference_draft(
    payload: ManualPreferenceDraftCreate, semester_id: int = Query(...), db: Session = Depends(get_db),
) -> dict:
    _semester_id(db, semester_id)
    lecturer = db.get(Lecturer, payload.lecturer_id)
    if not lecturer:
        raise HTTPException(404, "Không tìm thấy giảng viên.")
    parts = payload.parts if payload.context_type == "MIXED" else [payload]
    if payload.context_type == "MIXED" and (len(parts) < 2 or {part.context_type for part in parts} != {"TEACHING", "SEMINAR"}):
        raise HTTPException(422, "MIXED phải tách thành ít nhất một phần lịch dạy và một phần seminar.")
    items = [NormalizedPreferenceDraft(**_manual_draft_values(part, lecturer, semester_id)) for part in parts]
    for item, part in zip(items, parts):
        item.target = {**item.target, '_provenance': {field: {'origin': 'HUMAN_ENTERED' if getattr(item,field,None) not in (None,[], '') else 'UNKNOWN'} for field in SEMANTIC_FIELDS-{'target'}}}
        validation = validate_preference_draft(item, db)
        if part.status == 'CONFIRMED' and not validation['is_confirmable']:
            raise HTTPException(422, {'code':'PREFERENCE_DRAFT_NOT_READY', **validation})
        item.status = part.status if validation['is_confirmable'] else 'NEEDS_REVIEW'
        item.needs_review = not validation['is_confirmable']
    db.add_all(items); db.commit()
    return {"ids": [item.id for item in items], "created": len(items), "atomic_split": payload.context_type == "MIXED"}


@router.post("/preference-drafts/{draft_id}/validate")
def validate_draft_edit(draft_id: int, payload: PreferenceDraftUpdate, semester_id: int = Query(...), db: Session = Depends(get_db)):
    item = db.get(NormalizedPreferenceDraft, draft_id)
    if not item or item.semester_id != semester_id:
        raise HTTPException(404, 'Không tìm thấy bản nháp trong kỳ học.')
    data = {**draft_values(item), **payload.model_dump(exclude_unset=True), 'semester_id':semester_id}
    if 'numeric_value' in payload.model_fields_set:
        data['target']={k:v for k,v in (data.get('target') or {}).items() if k not in {'value','min','max'}}
    # Changing period values deliberately replaces existing alternatives.
    if data.get('periods'):
        data['target'] = {**(data.get('target') or {})}
        data['target'].pop('period_alternatives', None)
    if item.status == 'REJECTED': data['status'] = 'REJECTED'
    return validate_preference_draft(data, db)


@router.patch("/preference-drafts/{draft_id}")
def update_preference_draft(
    draft_id: int, payload: PreferenceDraftUpdate, semester_id: int = Query(...), db: Session = Depends(get_db),
) -> dict:
    item = db.get(NormalizedPreferenceDraft, draft_id)
    if not item or item.semester_id != semester_id:
        raise HTTPException(404, "Không tìm thấy bản nháp nguyện vọng.")
    changes = payload.model_dump(exclude_unset=True)
    for field in ('weight','hardness','constraint_type','status'):
        if field in changes and changes[field] is None:
            raise HTTPException(422,{'code':'MISSING_FIELD','field':field,'message':'Không được bỏ trống giá trị này.'})
    if 'periods' in changes and changes['periods'] is None: changes['periods']=[]
    old_status = item.status
    old_values = draft_values(item)
    if changes.get('lecturer_id') and changes['lecturer_id']!=item.lecturer_id:
        from app.services.lecturer_master import relink_source_identity
        lecturer=db.get(Lecturer,changes['lecturer_id'])
        if not lecturer: raise HTTPException(422,'Giảng viên không tồn tại.')
        try: relink_source_identity(db,item,lecturer,semester_id)
        except ValueError as error:
            db.rollback();raise HTTPException(409,str(error)) from error
    if (item.applied_constraint_id or item.applied_seminar_id) and any(k in SEMANTIC_FIELDS or k=='status' for k in changes):
        raise HTTPException(409, {'code':'PREFERENCE_ALREADY_APPLIED','message':'Bản nháp đã áp dụng; chỉnh ràng buộc đang hoạt động riêng.'})
    old_context = item.context_type
    for field in ("start_date", "end_date"):
        if field in changes:
            try:
                changes[field] = date.fromisoformat(changes[field]) if changes[field] else None
            except ValueError as error:
                raise HTTPException(422, f"{field} không hợp lệ.") from error
    if "periods" in changes and any(period < 1 or period > 15 for period in changes["periods"]):
        raise HTTPException(422, "Tiết phải nằm trong 1–15.")
    for field, value in changes.items():
        setattr(item, field, value)
    if "context_type" in changes:
        item.context_confirmed = True
        item.context_confidence = "HIGH"
        if changes["context_type"] == "MIXED":
            item.needs_review = True
            item.status = "NEEDS_REVIEW"
            item.review_reason = "MIXED phải tách thành các rule nguyên tử trước khi Apply."
        elif old_context == "SEMINAR" and changes["context_type"] == "TEACHING":
            item.seminar_link = None
            if item.constraint_type in {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}:
                item.constraint_type = "RAW_NOTE"
                item.needs_review = True
                item.status = "NEEDS_REVIEW"
    context = item.context_type
    compatible = (
        context == "TEACHING" and item.constraint_type not in {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}
    ) or (
        context == "SEMINAR" and item.constraint_type in {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}
    )
    if not compatible and context != "MIXED":
        item.needs_review = True
        item.status = "NEEDS_REVIEW"
        item.review_reason = "Loại rule chưa phù hợp ngữ cảnh đã chọn."
    if item.lecturer_id and compatible and item.constraint_type not in {"RAW_NOTE", "SEMINAR_NOTE"} and context != "MIXED" and item.status == "CONFIRMED":
        item.needs_review = False
        item.review_reason = None
    if "status" in changes:
        if changes["status"] == "REJECTED":
            item.status = "REJECTED"
            item.needs_review = False
            item.rejected_at = datetime.now(timezone.utc)
            item.rejected_reason = payload.rejected_reason or changes.get("review_reason") or item.rejected_reason
            item.review_reason = item.rejected_reason
        elif changes["status"] == "NEEDS_REVIEW":
            item.status = "NEEDS_REVIEW"
            item.needs_review = True
            item.rejected_at = None
            item.rejected_reason = None
            item.review_reason = None
    if "rejected_reason" in changes and changes.get("status") != "NEEDS_REVIEW":
        item.rejected_reason = payload.rejected_reason
    if item.start_date and item.end_date and item.end_date < item.start_date:
        raise HTTPException(422, "Ngày kết thúc phải không trước ngày bắt đầu.")
    target = {**(item.target or {}), "day_scope": item.day_scope, "periods": item.periods or []}
    target.pop("weekday", None)
    target.pop("slots", None)
    weekdays = _scope_weekdays(item.day_scope) if item.day_scope else []
    if item.day_scope in {"ALL_WEEKDAYS", "ALL_DAYS"}:
        target["slots"] = [{"weekday": weekday, "periods": item.periods or []} for weekday in weekdays]
    elif weekdays:
        target["weekday"] = weekdays[0]
    if target.get("period_alternatives"):
        if item.periods:
            target.pop("period_alternatives", None)
        else:
            target["slots"] = [{"weekday": day, "periods": periods} for day in weekdays for periods in target["period_alternatives"]]
    if item.start_date:
        target["start_date"] = item.start_date.isoformat()
    else:
        target.pop("start_date", None)
    if item.end_date:
        target["end_date"] = item.end_date.isoformat()
    else:
        target.pop("end_date", None)
    item.target = target
    item.target["context_type"] = context
    if context == "TEACHING":
        item.target.pop("seminar_link", None)
    else:
        item.target["seminar_link"] = item.seminar_link
    if item.numeric_value is not None:
        item.target = {**item.target, "value": item.numeric_value}
        item.target.pop("min", None)
        item.target.pop("max", None)
        item.target["min" if item.constraint_type == "MIN_CLASSES" else "max"] = item.numeric_value
    elif 'numeric_value' in changes:
        item.target={k:v for k,v in item.target.items() if k not in {'value','min','max'}}
    changed = {field for field in SEMANTIC_FIELDS & changes.keys() if old_values.get(field) != getattr(item,field,None)}
    try:
        item.status = transition_status(old_status, changes.get('status'), bool(changed))
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, {'code':str(error),'message':'Khôi phục về Cần xác nhận trước khi xác nhận lại.'}) from error
    provenance = dict((item.target or {}).get('_provenance',{}))
    for field in changed:
        provenance[field] = {'origin':'HUMAN_ENTERED' if getattr(item,field,None) not in (None,[],'') else 'UNKNOWN'}
    item.target = {**item.target,'_provenance':provenance}
    item.context_confirmed = item.context_confirmed or bool(changed)
    validation = validate_preference_draft(item, db)
    if item.status == 'CONFIRMED' and not validation['is_confirmable']:
        db.rollback()
        raise HTTPException(422, {'code':'PREFERENCE_DRAFT_NOT_READY', **validation})
    if item.status not in {'CONFIRMED','REJECTED'} and not validation['is_confirmable']:
        item.status='NEEDS_REVIEW'
        item.confidence='LOW'
    item.needs_review = item.status not in {'CONFIRMED','REJECTED'}
    if item.status=='CONFIRMED':
        item.target = {**item.target,'_provenance':{field:{**entry,'confirmed':True} for field,entry in provenance.items()}}
    elif changed and old_status=='CONFIRMED':
        item.review_reason='Nội dung đã thay đổi; cần xác nhận lại.'
    db.commit()
    db.refresh(item)
    return _draft_payload(item)


@router.post("/preference-drafts/confirm-high")
def confirm_high_preference_drafts(semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    _semester_id(db, semester_id)
    items = db.scalars(select(NormalizedPreferenceDraft).where(
        NormalizedPreferenceDraft.semester_id == semester_id,
        NormalizedPreferenceDraft.confidence == "HIGH",
        NormalizedPreferenceDraft.needs_review.is_(False),
        NormalizedPreferenceDraft.status.not_in(("CONFIRMED", "REJECTED")),
    )).all()
    confirmed = 0
    for item in items:
        if validate_preference_draft(item, db)['is_confirmable']:
            item.status = "CONFIRMED"
            confirmed += 1
    db.commit()
    return {"confirmed": confirmed}


def _scope_weekdays(scope: str) -> list[int]:
    if scope == "ALL_WEEKDAYS":
        return [2, 3, 4, 5, 6]
    if scope == "ALL_DAYS":
        return [2, 3, 4, 5, 6, 7, 8]
    if scope == "CN":
        return [8]
    return [int(scope[1:])] if scope and scope.startswith("T") else []


@router.post("/preference-drafts/apply")
def apply_preference_drafts(
    payload: PreferenceDraftApply, semester_id: int = Query(...), db: Session = Depends(get_db),
) -> dict:
    _semester_id(db, semester_id)
    items = db.scalars(select(NormalizedPreferenceDraft).where(
        NormalizedPreferenceDraft.id.in_(payload.draft_ids),
        NormalizedPreferenceDraft.semester_id == semester_id,
    )).all()
    if len(items) != len(set(payload.draft_ids)):
        raise HTTPException(404, "Có bản nháp không thuộc kỳ học này.")
    active_preference = db.get(Semester, semester_id).active_preference_source_id
    if any((item.source_version_id is not None and item.source_version_id != active_preference) or (item.target or {}).get('_stale_source_reference') for item in items):
        raise HTTPException(422, {"code": "SOURCE_CHANGED_REVIEW_REQUIRED", "message": "Bản nháp thuộc nguồn cũ hoặc có tham chiếu cũ; tạo lại hoặc rà soát nguồn hiện hành."})
    invalid = [item.id for item in items if item.status != "CONFIRMED" or item.needs_review or not validate_preference_draft(item, db)['is_confirmable']]
    invalid.extend(item.id for item in items if item.draft_kind == "CONSTRAINT" and (not item.lecturer_id or item.constraint_type in {"RAW_NOTE", "SEMINAR_NOTE"} or item.context_type == "MIXED"))
    supported_types = {
        "UNAVAILABLE", "AVOID_PERIOD", "PREFERRED_PERIOD", "PREFERRED_DAYS", "AVOID_DAYS", "PREFER_LOW_WORKLOAD", "PREFER_COMPACT_SCHEDULE", "PREFER_CONSECUTIVE_PERIODS",
        "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK",
        "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "SEMINAR_COMMITMENT"
    }
    invalid.extend(item.id for item in items if item.draft_kind == "CONSTRAINT" and item.constraint_type not in supported_types)
    seminar_types = {"SEMINAR_COMMITMENT", "SEMINAR_NOTE"}
    invalid.extend(
        item.id
        for item in items
        if item.draft_kind == "CONSTRAINT"
        and (
            ((item.context_type or "TEACHING") == "TEACHING" and item.constraint_type in seminar_types)
            or ((item.context_type or "TEACHING") == "SEMINAR" and item.constraint_type not in seminar_types)
        )
    )
    if invalid:
        raise HTTPException(422, {"code": "PREFERENCE_DRAFT_NOT_READY", "draft_ids": sorted(set(invalid))})
    type_map = {
        "UNAVAILABLE": "unavailable",
        "AVOID_PERIOD": "avoid",
        "PREFERRED_PERIOD": "prefer_period",
        "PREFERRED_DAYS": "preferred_days",
        "AVOID_DAYS": "avoid_days",
        "PREFER_LOW_WORKLOAD": "prefer_low_workload",
        "PREFER_COMPACT_SCHEDULE": "prefer_compact_schedule",
        "PREFER_CONSECUTIVE_PERIODS": "prefer_consecutive_periods",
        "MIN_FREE_MORNING_PER_WEEK": "min_free_morning_per_week",
        "MIN_CLASSES": "min_classes",
        "MAX_CLASSES": "max_classes",
        "MAX_SESSIONS_PER_DAY": "max_sessions_per_day",
        "MAX_DAYS_PER_WEEK": "max_days_per_week",
        "REQUIRED_ASSIGNMENT": "required_assignment",
        "FORBIDDEN_ASSIGNMENT": "forbidden_assignment",
        "SEMINAR_COMMITMENT": "seminar",
    }
    created_constraints = 0
    created_seminars = 0
    try:
        for item in items:
            if item.applied_constraint_id or item.applied_seminar_id or item.status == "REJECTED":
                continue
            if item.draft_kind == "SHARED_SEMINAR":
                target = item.target or {}
                alternatives = [
                    {"weekday": weekday, "periods": periods}
                    for scope in target.get("day_scopes", [])
                    for weekday in _scope_weekdays(scope)
                    for periods in target.get("period_blocks", [])
                ]
                seminar = Seminar(
                    semester_id=semester_id, source_version_id=item.source_version_id, name=target.get("name") or "Shared seminar", chair_name="",
                    members=target.get("member_ids") or [], alternatives=alternatives,
                    hardness=item.hardness, weight=item.weight,
                )
                db.add(seminar); db.flush(); item.applied_seminar_id = seminar.id; created_seminars += 1
            else:
                constraint = Constraint(
                    semester_id=semester_id, source_version_id=item.source_version_id, lecturer_id=item.lecturer_id,
                    name=describe_preference(item.constraint_type, item.target or {}),
                    constraint_type=type_map.get(item.constraint_type, item.constraint_type),
                    hardness=item.hardness, weight=item.weight,
                    target={**(item.target or {}), "context_type": item.context_type or "TEACHING", "seminar_link": item.seminar_link},
                    raw_text=item.raw_text, confirmed=True, active=True,
                )
                db.add(constraint); db.flush(); item.applied_constraint_id = constraint.id; created_constraints += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"applied": len(items), "constraints": created_constraints, "seminars": created_seminars}


@router.get("/dashboard")
def get_dashboard(
    semester_id: int | None = Query(None),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    if isinstance(run_id, Session):
        db = run_id
        run_id = None
    return dashboard(db, _semester_id(db, semester_id), run_id=run_id)


@router.get("/lecturers")
def get_lecturers(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "code": item.code,
            "name": item.canonical_name,
            "aliases": item.aliases,
            "confirmed": item.confirmed,
            "status": item.status,
            "department": item.department,
            "email": item.email,
            "note": item.note,
            "max_credits": item.max_credits,
        }
        for item in db.scalars(
            select(Lecturer)
            .where((Lecturer.status != "INACTIVE") | (Lecturer.status.is_(None)))
            .order_by(Lecturer.canonical_name)
        ).all()
    ]


@router.post("/lecturers/{lecturer_id}/aliases")
def resolve_lecturer_alias(
    lecturer_id: int,
    payload: AliasResolution,
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Attach an explicit alias to one master lecturer and resolve matching review issues."""
    _semester_id(db, semester_id)
    lecturer = db.get(Lecturer, lecturer_id)
    if not lecturer:
        raise HTTPException(404, "Không tìm thấy giảng viên.")
    alias = payload.alias.strip()
    try:
        confirm_alias(db, lecturer, alias)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    aliases = {item.strip() for item in (lecturer.aliases or []) if item.strip()}
    aliases.add(alias)
    lecturer.aliases = sorted(aliases)
    from app.services.lecturer_master import relink_source_identity,normalize_identity,source_identity_key
    linked=set()
    try:
        for draft in db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id==_semester_id(db,semester_id))):
            key=source_identity_key(draft.lecturer_alias,draft.lecturer_code)
            if normalize_identity(draft.lecturer_alias or '')==normalize_identity(alias) and key not in linked:
                relink_source_identity(db,draft,lecturer,_semester_id(db,semester_id));linked.add(key)
    except ValueError as error:
        db.rollback();raise HTTPException(409,str(error)) from error
    db.commit()
    return {"lecturer_id": lecturer.id, "aliases": lecturer.aliases, "resolved": True}


@router.get("/readiness")
def get_readiness(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    sid = _semester_id(db, semester_id)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id == sid)).all()
    course_ids = {item.course_id for item in classes}
    capability_rows = db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.course_id.in_(course_ids), or_(LecturerCourseCapability.source.is_(None), LecturerCourseCapability.source != "HYPOTHETICAL_ALL"))).all() if course_ids else []
    capable_courses = {item.course_id for item in capability_rows if item.allowed and item.confirmed}
    issues = db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == sid)).all()
    constraints = db.scalars(select(Constraint).where(Constraint.semester_id == sid)).all()
    preference_drafts = db.scalars(select(NormalizedPreferenceDraft).where(NormalizedPreferenceDraft.semester_id == sid, or_(NormalizedPreferenceDraft.source_version_id.is_(None), NormalizedPreferenceDraft.source_version_id == db.get(Semester, sid).active_preference_source_id))).all()
    relevant_ids = {item.assigned_lecturer_id for item in classes if item.assigned_lecturer_id}
    relevant_ids.update(item.lecturer_id for item in constraints if item.lecturer_id)
    from app.api.lecturer_routes import review_lecturers
    identity_review=review_lecturers(sid,db)
    latest = latest_current_run(db, sid)
    warnings = []
    for issue in issues:
        if issue.code in {"LECTURER_IDENTITY_AMBIGUOUS", "PARTIAL_MERGE_CANDIDATE", "SEMESTER_METADATA_MISMATCH", "SOURCE_CHANGED_REVIEW_REQUIRED"}:
            warnings.append({"code": issue.code, "message": issue.message})
    for message in identity_review['blockers']:
        if not any(w['message']==message for w in warnings):
            warnings.append({'code':'LECTURER_IDENTITY_AMBIGUOUS','message':message})
    review_constraints = [item for item in constraints if item.active and item.constraint_type.casefold() in {"raw_preference", "preferred_assignment", "compact_schedule"}]
    if review_constraints:
        warnings.append({"code": "MALFORMED_CONSTRAINT", "message": f"{len(review_constraints)} ràng buộc chưa chuẩn hóa cần trưởng bộ môn rà soát."})
    pending_drafts = [item for item in preference_drafts if item.status!='REJECTED' and (item.needs_review or item.status in {"DRAFT", "NEEDS_REVIEW"})]
    if pending_drafts:
        warnings.append({"code": "PREFERENCE_DRAFT_REVIEW_REQUIRED", "message": f"{len(pending_drafts)} nguyện vọng đang là bản nháp hoặc cần rà soát trước khi áp dụng."})
    missing_rooms = sum(1 for item in classes for session in item.sessions if not session.room.strip())
    if missing_rooms:
        warnings.append({"code": "MISSING_ROOM", "message": f"{missing_rooms} meeting chưa có phòng; mặc định không ghép lớp."})
    if latest and (latest.summary or {}).get("code"):
        warnings.append({"code": latest.summary["code"], "message": "Solver gần nhất đang có điều kiện blocking cần rà soát."})
    warnings.extend(source_blockers(db, sid))
    return {
        "ready": not source_blockers(db, sid) and not any(item["code"] in {"LECTURER_IDENTITY_AMBIGUOUS", "PARTIAL_MERGE_CANDIDATE", "LOCKED_ASSIGNMENT_CONFLICT"} for item in warnings),
        "lecturers": {"total": identity_review['total_lecturers'], "resolved": identity_review['ready_count'], "need_review": identity_review['needs_review_count']},
        "teaching_groups": len(classes),
        "meetings": sum(len(item.sessions) for item in classes),
        "valid_meetings": all(item.sessions for item in classes),
        "groups_without_capability": sum(item.course_id not in capable_courses for item in classes),
        "warnings": warnings,
    }


@router.get("/workload")
def get_workload(
    semester_id: int | None = Query(None),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    if isinstance(run_id, Session):
        db = run_id
        run_id = None
    sid = _semester_id(db, semester_id)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id == sid)).all()
    class_by_id = {c.id: c for c in classes}
    course_ids = {item.course_id for item in classes}
    lecturer_ids = {item.assigned_lecturer_id for item in classes if item.assigned_lecturer_id}
    if course_ids:
        lecturer_ids.update(
            item.lecturer_id
            for item in db.scalars(select(LecturerCourseCapability).where(
                LecturerCourseCapability.course_id.in_(course_ids),
                or_(LecturerCourseCapability.source.is_(None), LecturerCourseCapability.source != "HYPOTHETICAL_ALL"),
            )).all()
        )
    run = None
    if run_id is not None:
        run = db.get(OptimizationRun, run_id)
        if run and run.semester_id != sid:
            run = None
    if not run and run_id is None:
        run = latest_current_run(db, sid)

    if run and run.status in {"optimal", "feasible"}:
        assignments = db.scalars(select(Assignment).where(Assignment.run_id == run.id)).all()
        lecturer_ids.update(a.lecturer_id for a in assignments)
        lecturers = db.scalars(select(Lecturer).where(Lecturer.id.in_(lecturer_ids)).order_by(Lecturer.canonical_name)).all() if lecturer_ids else []
        lec_assigned = defaultdict(list)
        for a in assignments:
            if a.class_id in class_by_id:
                lec_assigned[a.lecturer_id].append(class_by_id[a.class_id])
        result = []
        for lecturer in lecturers:
            assigned = lec_assigned.get(lecturer.id, [])
            meetings = [session for item in assigned for session in item.sessions]
            result.append({
                "lecturer_id": lecturer.id, "lecturer": lecturer.canonical_name,
                "teaching_groups": len(assigned), "meetings": len(meetings),
                "periods": sum(session.end_period - session.start_period + 1 for session in meetings),
                "credits": sum(item.credits for item in assigned),
            })
        return result

    lecturers = db.scalars(select(Lecturer).where(Lecturer.id.in_(lecturer_ids)).order_by(Lecturer.canonical_name)).all() if lecturer_ids else []
    result = []
    for lecturer in lecturers:
        assigned = [item for item in classes if item.assigned_lecturer_id == lecturer.id]
        meetings = [session for item in assigned for session in item.sessions]
        result.append({
            "lecturer_id": lecturer.id, "lecturer": lecturer.canonical_name,
            "teaching_groups": len(assigned), "meetings": len(meetings),
            "periods": sum(session.end_period - session.start_period + 1 for session in meetings),
            "credits": sum(item.credits for item in assigned),
        })
    return result


@router.get("/classes")
def get_classes(
    semester_id: int | None = Query(None),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    if isinstance(run_id, Session):
        db = run_id
        run_id = None
    sid = _semester_id(db, semester_id)
    items = db.scalars(
        select(ClassSection)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
        .where(ClassSection.semester_id == sid).order_by(ClassSection.id)
    ).all()
    run = None
    if run_id is not None:
        run = db.get(OptimizationRun, run_id)
        if run and run.semester_id != sid:
            run = None
    if not run and run_id is None:
        run = latest_current_run(db, sid)
    ass_by_class = {}
    if run and run.status in {"optimal", "feasible"}:
        for a in db.scalars(select(Assignment).options(selectinload(Assignment.lecturer)).where(Assignment.run_id == run.id)):
            ass_by_class[a.class_id] = a

    result = []
    for item in items:
        ass = ass_by_class.get(item.id)
        if item.locked_assignment:
            lec_id = item.assigned_lecturer_id
            lec_name = item.assigned_lecturer.canonical_name if item.assigned_lecturer else None
            ass_src = item.assignment_source or "MANUAL"
        elif run and run.status in {"optimal", "feasible"}:
            if ass and ass.lecturer_id:
                lec_id = ass.lecturer_id
                lec_name = ass.lecturer.canonical_name if ass.lecturer else None
                ass_src = "SOLVER"
            else:
                lec_id = None
                lec_name = None
                ass_src = None
        else:
            lec_id = item.assigned_lecturer_id
            lec_name = item.assigned_lecturer.canonical_name if item.assigned_lecturer else None
            ass_src = item.assignment_source
        result.append({
            "id": item.id,
            "source_version_id": item.source_version_id,
            "provenance_status": "VERIFIED" if item.source_version_id else "LEGACY_UNVERIFIED",
            "course_id": item.course_id,
            "course_code": item.course.code,
            "course_name": item.course.name,
            "class_code": item.class_code,
            "credits": item.credits,
            "merged_group_id": item.merged_group_id,
            "merged_confirmed": item.merged_confirmed,
            "merge_status": item.merge_status,
            "locked_assignment": item.locked_assignment,
            "assignment_source": ass_src,
            "lecturer_id": lec_id,
            "lecturer": lec_name,
            "sessions": [
                {
                    "source_version_id": session.source_version_id, "source_rows": session.source_rows or [session.source_row],
                    "weekday": session.weekday,
                    "start_period": session.start_period,
                    "end_period": session.end_period,
                    "room": session.room,
                    "start_date": session.start_date,
                    "end_date": session.end_date,
                    "raw_weeks": session.raw_weeks,
                    "active_weeks": session.active_weeks,
                }
                for session in item.sessions
            ],
        })
    return result

@router.get("/classes/{class_id}/candidates")
def class_candidates(class_id: int, semester_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    group = db.get(ClassSection, class_id)
    if not group or group.semester_id != semester_id: raise HTTPException(404, "Không tìm thấy lớp.")
    result = []
    for item in db.scalars(select(Lecturer).order_by(Lecturer.id)):
        check = check_assignment_change(db, semester_id, class_id, item.id)
        current = db.scalars(select(ClassSection).where(ClassSection.semester_id == semester_id, ClassSection.assigned_lecturer_id == item.id)).all()
        result.append({
            "lecturer_id": item.id,
            "status": "ELIGIBLE" if check["valid"] else check["blocking_reasons"][0],
            "workload": {"teaching_groups": len(current), "credits": sum(row.credits for row in current)},
        })
    return result

@router.post("/classes/{class_id}/assignment/check")
def check_assignment(class_id: int, payload: dict, semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    group = db.get(ClassSection, class_id)
    if not group or group.semester_id != semester_id:
        raise HTTPException(404, "Không tìm thấy lớp.")
    return check_assignment_change(db, semester_id, class_id, int(payload["lecturer_id"]))

@router.patch("/classes/{class_id}/assignment")
def manual_assignment(class_id: int, payload: dict, semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    allow_override = bool(payload.get("allow_override_lock", False))
    override_reason = str(payload.get("override_reason", ""))
    result = apply_manual_assignment(
        db,
        semester_id,
        class_id,
        int(payload["lecturer_id"]),
        bool(payload.get("lock", False)),
        allow_override_lock=allow_override,
        override_reason=override_reason,
    )
    if not result["valid"]: raise HTTPException(422, result)
    return result

@router.get("/classes/unassigned")
def list_unassigned_classes(
    semester_id: int = Query(...),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.services.unassigned_diagnostics import diagnose_unassigned_classes
    return diagnose_unassigned_classes(db, semester_id, run_id)

@router.get("/classes/{class_id}/candidate-analysis")
def candidate_analysis(
    class_id: int,
    semester_id: int = Query(...),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.services.unassigned_diagnostics import get_candidate_analysis
    return get_candidate_analysis(db, semester_id, class_id, run_id)

@router.patch("/classes/{class_id}/resolution-status")
def update_class_resolution(
    class_id: int,
    payload: dict,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.unassigned_diagnostics import update_resolution_status
    status = payload.get("status", "NEW")
    notes = payload.get("notes")
    try:
        return update_resolution_status(db, semester_id, class_id, status, notes)
    except ValueError as err:
        raise HTTPException(422, str(err)) from err

@router.post("/classes/{class_id}/override-lock")
def override_lock(
    class_id: int,
    payload: dict,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """Explicit human-in-the-loop lock override endpoint."""
    from app.services.unassigned_diagnostics import override_lock_assignment
    lecturer_id = payload.get("lecturer_id")
    reason = payload.get("reason", "")
    user = payload.get("user", "Human Operator")
    lock = bool(payload.get("lock", True))
    if not lecturer_id:
        raise HTTPException(422, "lecturer_id is required.")
    try:
        return override_lock_assignment(db, semester_id, class_id, int(lecturer_id), reason, user=user, lock=lock)
    except ValueError as err:
        raise HTTPException(422, str(err)) from err

@router.post("/classes/{class_id}/lock")
def lock_assignment(class_id: int, semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    group=db.get(ClassSection,class_id)
    if not group or group.semester_id!=semester_id or not group.assigned_lecturer_id: raise HTTPException(422,"Chưa có phân công hợp lệ để khóa.")
    result=apply_manual_assignment(db,semester_id,class_id,group.assigned_lecturer_id,True)
    if not result["valid"]: raise HTTPException(422,result)
    return result

@router.post("/classes/{class_id}/unlock")
def unlock_assignment(class_id: int, semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    group=db.get(ClassSection,class_id)
    if not group or group.semester_id!=semester_id: raise HTTPException(404,"Không tìm thấy lớp.")
    group.locked_assignment=False; db.commit(); return {"id":class_id,"locked":False}



@router.patch("/merged-groups")
def decide_merged_group(payload: MergedDecision, semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(
        select(ClassSection).where(ClassSection.merged_group_id == payload.merged_group_id, ClassSection.semester_id == _semester_id(db, semester_id))
    ).all()
    if not items:
        raise HTTPException(404, "Không tìm thấy nhóm ghép.")
    for item in items:
        item.merged_confirmed = payload.confirmed
        item.merge_status = "confirmed" if payload.confirmed else "rejected"
    db.commit()
    return {"merged_group_id": payload.merged_group_id, "confirmed": payload.confirmed, "classes": len(items)}


@router.post("/classes/merge")
def merge_classes(
    payload: MergeClassesRequest,
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    sid = _semester_id(db, semester_id)
    classes = db.scalars(
        select(ClassSection)
        .options(selectinload(ClassSection.sessions), selectinload(ClassSection.course))
        .where(
            ClassSection.id.in_(payload.class_ids),
            ClassSection.semester_id == sid,
        )
    ).all()
    if len(classes) < 2:
        raise HTTPException(400, "Cần ít nhất 2 lớp để thực hiện ghép lớp.")
    first = classes[0]
    for other in classes[1:]:
        if not are_classes_mergeable(first, other):
            raise HTTPException(
                400,
                f"Không thể ghép lớp {first.class_code} và {other.class_code}: lịch học không đồng bộ (khác thứ, khác tiết hoặc lệch buổi).",
            )
    group_id = payload.merged_group_id or f"MG-M{uuid4().hex[:6].upper()}"
    for item in classes:
        item.merged_group_id = group_id
        item.merged_confirmed = True
        item.merge_status = "confirmed"
    db.commit()
    return {
        "merged_group_id": group_id,
        "confirmed": True,
        "classes": len(classes),
        "class_ids": [c.id for c in classes],
        "class_codes": [c.class_code for c in classes],
    }


@router.post("/classes/unmerge")
def unmerge_classes(
    payload: UnmergeClassesRequest,
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    sid = _semester_id(db, semester_id)
    affected_groups = set()
    if payload.merged_group_id:
        affected_groups.add(payload.merged_group_id)
    elif payload.class_ids:
        found_classes = db.scalars(select(ClassSection).where(ClassSection.id.in_(payload.class_ids), ClassSection.semester_id == sid)).all()
        for c in found_classes:
            if c.merged_group_id:
                affected_groups.add(c.merged_group_id)
    else:
        raise HTTPException(400, "Cần cung cấp class_ids hoặc merged_group_id để hủy ghép lớp.")

    query = select(ClassSection).where(ClassSection.semester_id == sid)
    if payload.merged_group_id:
        query = query.where(ClassSection.merged_group_id == payload.merged_group_id)
    elif payload.class_ids:
        query = query.where(ClassSection.id.in_(payload.class_ids))

    classes = db.scalars(query).all()
    for item in classes:
        item.merged_group_id = None
        item.merged_confirmed = False
        item.merge_status = "single"
    db.flush()

    # Clean up any remaining groups that have < 2 classes
    for gid in affected_groups:
        remaining = db.scalars(
            select(ClassSection).where(
                ClassSection.semester_id == sid,
                ClassSection.merged_group_id == gid,
            )
        ).all()
        if len(remaining) < 2:
            for rem in remaining:
                rem.merged_group_id = None
                rem.merged_confirmed = False
                rem.merge_status = "single"

    db.commit()
    return {
        "unmerged": len(classes),
        "class_ids": [c.id for c in classes],
    }


def _meeting_signature(session: ClassSession) -> tuple:
    return (
        session.weekday,
        session.start_period,
        session.end_period,
        (session.room or "").casefold(),
        tuple(session.active_weeks or []),
    )


@router.get("/merge-candidates")
def get_merge_candidates(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    sid = _semester_id(db, semester_id)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions), selectinload(ClassSection.course)).where(ClassSection.semester_id == sid)).all()
    result = []
    by_group: dict[str, list[ClassSection]] = {}
    for item in classes:
        if item.merged_group_id:
            by_group.setdefault(item.merged_group_id, []).append(item)
    for group_id, items in by_group.items():
        signatures = {_meeting_signature(session) for item in items for session in item.sessions}
        result.append({
            "kind": "FULL", "id": group_id, "status": items[0].merge_status,
            "classes": [{"id": item.id, "class_code": item.class_code, "course": item.course.name if item.course else ""} for item in items],
            "matched_meetings": len(signatures), "different_meetings": 0,
            "meeting_details": [
                {"weekday": session.weekday, "periods": f"{session.start_period}-{session.end_period}", "room": session.room, "weeks": session.active_weeks or []}
                for session in items[0].sessions
            ],
        })
    for index, left in enumerate(classes):
        left_signatures = {_meeting_signature(item) for item in left.sessions if item.room and item.room.strip()}
        if not left_signatures:
            continue
        for right in classes[index + 1:]:
            if left.course_id != right.course_id:
                continue
            right_signatures = {_meeting_signature(item) for item in right.sessions if item.room and item.room.strip()}
            matched = left_signatures.intersection(right_signatures)
            if not matched or left_signatures == right_signatures:
                continue
            result.append({
                "kind": "PARTIAL", "id": f"partial-{left.id}-{right.id}", "status": "review",
                "classes": [{"id": left.id, "class_code": left.class_code, "course": left.course.name}, {"id": right.id, "class_code": right.class_code, "course": right.course.name}],
                "matched_meetings": len(matched),
                "different_meetings": len(left_signatures - matched) + len(right_signatures - matched),
                "review_only": True,
                "meeting_details": {
                    "matched": [{"weekday": item[0], "periods": f"{item[1]}-{item[2]}", "room": item[3], "weeks": list(item[4])} for item in sorted(matched)],
                    "left_only": [{"weekday": item[0], "periods": f"{item[1]}-{item[2]}", "room": item[3], "weeks": list(item[4])} for item in sorted(left_signatures - matched)],
                    "right_only": [{"weekday": item[0], "periods": f"{item[1]}-{item[2]}", "room": item[3], "weeks": list(item[4])} for item in sorted(right_signatures - matched)],
                },
            })
    return result


@router.get("/constraints")
def get_constraints(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "constraint_type": item.constraint_type,
            "hardness": item.hardness,
            "weight": item.weight,
            "lecturer_id": item.lecturer_id,
            "lecturer": item.lecturer.canonical_name if item.lecturer else None,
            "target": item.target,
            "normalized_text": describe_preference(item.constraint_type, item.target),
            "raw_text": item.raw_text,
            "confirmed": item.confirmed,
            "active": item.active,
        }
        for item in db.scalars(
            select(Constraint).where(Constraint.semester_id == _semester_id(db, semester_id)).options(selectinload(Constraint.lecturer)).order_by(Constraint.id)
        ).all()
    ]


@router.post("/constraints")
def create_constraint(payload: ConstraintCreate, semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    item = Constraint(**payload.model_dump(), semester_id=_semester_id(db, semester_id))
    db.add(item)
    db.commit()
    return {"id": item.id, "created": True}


@router.patch("/constraints/{constraint_id}")
def update_constraint(
    constraint_id: int,
    payload: ConstraintUpdate,
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(Constraint, constraint_id)
    if not item or item.semester_id != _semester_id(db, semester_id):
        raise HTTPException(404, "Không tìm thấy ràng buộc.")
    if (item.target or {}).get('_stale_source_reference'):
        raise HTTPException(422, {"code": "SOURCE_CHANGED_REVIEW_REQUIRED", "message": "Ràng buộc thuộc nguồn cũ; tạo ràng buộc mới với nhóm lớp hiện hành."})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return {"id": item.id, "updated": True}


@router.delete("/constraints/{constraint_id}")
def delete_constraint(constraint_id: int, semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    item = db.get(Constraint, constraint_id)
    if not item or item.semester_id != _semester_id(db, semester_id):
        raise HTTPException(404, "Không tìm thấy ràng buộc.")
    db.delete(item)
    db.commit()
    return {"id": constraint_id, "deleted": True}


@router.post("/seminars")
def create_seminar(payload: SeminarCreate, semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    item = Seminar(
        name=payload.name,
        chair_name=payload.chair_name,
        members=payload.members,
        alternatives=payload.alternatives,
        weight=payload.weight,
        hardness=payload.hardness,
        semester_id=_semester_id(db, semester_id),
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "created": True}


@router.get("/seminars")
def get_seminars(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "chair_name": item.chair_name,
            "members": item.members,
            "alternatives": item.alternatives,
            "weight": item.weight,
            "hardness": item.hardness,
            "slots": item.alternatives,
        }
        for item in db.scalars(select(Seminar).where(Seminar.semester_id == _semester_id(db, semester_id)).order_by(Seminar.id)).all()
    ]


@router.post("/optimization/run")
def run_optimization(payload: OptimizationRequest, semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    try:
        sid = _semester_id(db, semester_id)
        if db.get(Semester, sid).active_schedule_source_id is None:
            raise SourceError("ACTIVE_SCHEDULE_REQUIRED", "Cần xem đối chiếu và xác nhận nguồn lịch trước khi chạy tối ưu.")
        run = solve(db, payload.time_limit_seconds, payload.confirm_merged_suggestions, sid)
    except SourceError as error:
        raise HTTPException(422, error.detail) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"run_id": run.id, "status": run.status, "score": run.score, "summary": run.summary}


@router.get("/optimization/runs")
def get_optimization_runs(semester_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    _semester_id(db, semester_id)
    return [
        {"id": run.id, "status": run.status, "score": run.score, "summary": run.summary, "created_at": run.created_at}
        for run in db.scalars(
            select(OptimizationRun)
            .where(OptimizationRun.semester_id == semester_id)
            .order_by(OptimizationRun.created_at.desc())
        ).all()
    ]


@router.get("/optimization/runs/{run_id}/diff")
def get_optimization_run_diff(run_id: int, semester_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    run = db.get(OptimizationRun, run_id)
    if not run or run.semester_id != semester_id:
        raise HTTPException(404, "Không tìm thấy phiên tối ưu.")
    if run.source_revision != db.get(Semester, semester_id).source_revision:
        return {"run_id": run.id, "historical": True, "archive": run.summary.get("archived_assignments", []), "changes": [], "assigned": 0, "unassigned": 0, "changed_assignments": 0, "new_problems": 0, "resolved_problems": 0, "previous_run_id": None}
    previous = db.scalar(select(OptimizationRun).where(
        current_run_predicate(db.get(Semester, semester_id)), OptimizationRun.id < run.id,
    ).order_by(OptimizationRun.id.desc()))
    current_rows = db.scalars(select(Assignment).options(selectinload(Assignment.lecturer), selectinload(Assignment.class_section)).where(Assignment.run_id == run.id)).all()
    before_rows = db.scalars(select(Assignment).options(selectinload(Assignment.lecturer)).where(Assignment.run_id == previous.id)).all() if previous else []
    before = {item.class_id: item for item in before_rows}
    after = {item.class_id: item for item in current_rows}
    changes = []
    for class_id in sorted(set(before).union(after)):
        left, right = before.get(class_id), after.get(class_id)
        if left and right and left.lecturer_id == right.lecturer_id:
            continue
        group = (right or left).class_section if right else db.get(ClassSection, class_id)
        changes.append({
            "class_id": class_id, "class_code": group.class_code if group else str(class_id),
            "before_lecturer": left.lecturer.canonical_name if left else None,
            "after_lecturer": right.lecturer.canonical_name if right else None,
            "source": right.source if right else None,
            "locked": right.locked if right else False,
        })
    current_unassigned = len((run.summary or {}).get("unassigned", []))
    previous_unassigned = len((previous.summary or {}).get("unassigned", [])) if previous else 0
    return {
        "run_id": run.id, "previous_run_id": previous.id if previous else None,
        "assigned": len(after), "unassigned": current_unassigned,
        "changed_assignments": len(changes), "changes": changes,
        "new_problems": max(0, current_unassigned - previous_unassigned),
        "resolved_problems": max(0, previous_unassigned - current_unassigned),
    }


@router.get("/assignments")
def get_assignments(
    semester_id: int | None = Query(None),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    if isinstance(run_id, Session):
        db = run_id
        run_id = None
    sid = _semester_id(db, semester_id)
    run = None
    if run_id is not None:
        run = db.get(OptimizationRun, run_id)
        if run and run.semester_id != sid:
            run = None
    if not run and run_id is None:
        run = latest_current_run(db, sid)
    latest = run.id if run else None
    if latest is None:
        return []
    items = db.scalars(
        select(Assignment)
        .where(Assignment.run_id == latest)
        .options(
            selectinload(Assignment.lecturer),
            selectinload(Assignment.class_section).selectinload(ClassSection.course),
            selectinload(Assignment.class_section).selectinload(ClassSection.sessions),
        )
    ).all()
    return [
        {
            "id": item.id,
            "class_id": item.class_id,
            "course_name": item.class_section.course.name,
            "class_code": item.class_section.class_code,
            "lecturer": item.lecturer.canonical_name,
            "locked": item.locked,
            "source": item.source,
            "sessions": [
                {
                    "weekday": session.weekday,
                    "periods": f"{session.start_period}-{session.end_period}",
                    "room": session.room,
                }
                for session in item.class_section.sessions
            ],
        }
        for item in items
    ]


@router.get("/conflicts")
def get_conflicts(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": issue.id,
            "severity": issue.severity,
            "code": issue.code,
            "message": issue.message,
            "source_file": issue.source_file,
            "source_sheet": issue.source_sheet,
            "source_row": issue.source_row,
            "field": issue.field,
            "suggestion": issue.suggestion,
            "raw_value": issue.raw_value, "source_version_id": issue.source_version_id, "details": issue.details, "resolution_status": issue.resolution_status,
        }
        for issue in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == _semester_id(db, semester_id), ValidationIssue.resolution_status != "SUPERSEDED").order_by(ValidationIssue.id)).all()
    ]

@router.get("/problems")
def get_problems(semester_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    _semester_id(db, semester_id)
    problems = {}
    def add(code, severity, entity_type, entity_id, message, reasons=None, lecturer_id=None, constraints=None):
        key = (code, entity_type, str(entity_id))
        problems.setdefault(key, {"code": code, "severity": severity, "entity_type": entity_type, "entity_id": str(entity_id), "lecturer_id": lecturer_id, "message": message, "reasons": reasons or [], "related_constraints": constraints or [], "resolvable": True})
    for issue in active_issues(db, semester_id):
        add(issue.code, "critical" if issue.severity == "error" else "warning", "validation_issue", issue.id, issue.message)
    for draft in db.scalars(select(NormalizedPreferenceDraft).where(
        NormalizedPreferenceDraft.semester_id == semester_id,
        NormalizedPreferenceDraft.needs_review.is_(True),
        or_(NormalizedPreferenceDraft.source_version_id.is_(None), NormalizedPreferenceDraft.source_version_id == db.get(Semester, semester_id).active_preference_source_id),
        NormalizedPreferenceDraft.status != "REJECTED",
    )):
        code = "MIXED_PREFERENCE_REQUIRES_SPLIT" if (draft.context_type or "TEACHING") == "MIXED" else "PREFERENCE_DRAFT_REVIEW_REQUIRED"
        add(code, "warning", "preference_draft", draft.id,
            draft.review_reason or "Nguyện vọng cần trưởng bộ môn rà soát trước khi áp dụng.",
            [{"source": f"{draft.source_sheet}!{draft.source_cell}", "raw_text": draft.raw_text}],
            lecturer_id=draft.lecturer_id)
    run = latest_current_run(db, semester_id)
    if run:
        summary = run.summary or {}
        if summary.get("code"):
            code = summary["code"]
            if code == "LOCKED_ASSIGNMENT_CONFLICT":
                readable_pairs = []
                for pair in summary.get("pairs", []):
                    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                        continue
                    left = db.get(ClassSection, pair[0])
                    right = db.get(ClassSection, pair[1])
                    if left and right and left.semester_id == semester_id and right.semester_id == semester_id:
                        readable_pairs.append({
                            "reason": f"{left.class_code} và {right.class_code} là hai phân công đã khóa bị trùng thời gian.",
                            "class_ids": [left.id, right.id],
                            "lecturer_id": left.assigned_lecturer_id,
                        })
                add(
                    code, "critical", "optimization_run", run.id,
                    "Solver bị chặn vì có phân công đã khóa bị trùng thời gian.",
                    readable_pairs or [{"reason": "Hãy rà soát các phân công đã khóa trước khi chạy lại solver."}],
                )
            else:
                add(code, "critical", "optimization_run", run.id, code, summary.get("pairs", []))
        for item in summary.get("unassigned", []):
            class_id = item.get("class_id")
            group = db.get(ClassSection, class_id)
            reasons = item.get("reasons", [])
            class_label = f"Lớp {group.class_code} ({group.course.name if group and group.course else ''})" if group else f"Lớp #{class_id}"
            add("UNASSIGNED", "warning", "class_section", class_id, f"{class_label} chưa được phân công.", reasons)
        for item in summary.get("unsupported_constraints", []):
            add("UNSUPPORTED_CONSTRAINT_TYPE", "warning", "constraint", item, f"Constraint không được hỗ trợ: {item}")
        for item in summary.get("invalid_constraints", []):
            add("UNSUPPORTED_CONSTRAINT_TYPE", "warning", "constraint", item, "Constraint có target không hợp lệ.")
    return list(problems.values())


@router.get("/exports/latest")
def download_export(
    semester_id: int | None = Query(None),
    mode: str = Query("draft", pattern="^(draft|final)$"),
    export_type: str = Query("detailed", pattern="^(detailed|matrix)$"),
    allow_unassigned_override: bool = Query(False),
    override_reason: str = Query(""),
    db: Session = Depends(get_db),
) -> FileResponse:
    directory = Path(tempfile.mkdtemp(prefix="huce-export-"))
    try:
        path = export_latest(
            db,
            directory,
            _semester_id(db, semester_id),
            mode=mode,
            export_type=export_type,
            allow_unassigned_override=allow_unassigned_override,
            override_reason=override_reason,
        )
    except ValueError as error:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )


@router.get("/exports/matrix")
def download_matrix_export(
    semester_id: int | None = Query(None),
    mode: str = Query("draft", pattern="^(draft|final)$"),
    allow_unassigned_override: bool = Query(False),
    override_reason: str = Query(""),
    db: Session = Depends(get_db),
) -> FileResponse:
    directory = Path(tempfile.mkdtemp(prefix="huce-matrix-export-"))
    try:
        path = export_matrix(
            db,
            directory,
            _semester_id(db, semester_id),
            mode=mode,
            allow_unassigned_override=allow_unassigned_override,
            override_reason=override_reason,
        )
    except ValueError as error:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        path,
        filename=path.name,

        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )


@router.get("/historical-evidence")
def list_historical_evidence(
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    sid = _semester_id(db, semester_id)
    records = db.scalars(
        select(HistoricalEvidence)
        .where(HistoricalEvidence.semester_id == sid)
        .order_by(HistoricalEvidence.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "profile_id": r.profile_id,
            "lecturer_id": r.lecturer_id,
            "source_text": r.source_text,
            "lecturer_code": r.lecturer_code,
            "source_row": r.source_row,
            "source_cell": r.source_cell,
            "evidence": r.evidence,
            "status": r.status,
            "human_confirmed": r.human_confirmed,
        }
        for r in records
    ]


@router.get("/semesters/{semester_id}/capability-readiness")
def get_capability_readiness(semester_id: int, db: Session = Depends(get_db)):
    from app.services.capability_resolution import CapabilityResolutionService
    sid = _semester_id(db, semester_id)
    return CapabilityResolutionService.evaluate_capability_readiness(db, sid)


@router.post("/semesters/{semester_id}/capabilities/import-matrix")
def import_capability_matrix(
    semester_id: int,
    file: UploadFile = File(...),
    sheet_name: str | None = Query(None),
    confirmed: bool = Query(True),
    db: Session = Depends(get_db),
):
    from app.services.capability_resolution import CapabilityResolutionService
    sid = _semester_id(db, semester_id)
    suffix = Path(file.filename or "matrix.xlsx").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        _copy_upload_limited(file, tmp_path)
    try:
        return CapabilityResolutionService.import_capability_matrix(
            db=db,
            file_path=tmp_path,
            semester_id=sid,
            sheet_name=sheet_name,
            confirmed=confirmed,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/semesters/{semester_id}/capabilities/learn-history")
def learn_historical_capabilities(
    semester_id: int,
    file: UploadFile = File(...),
    sheet_name: str | None = Query(None),
    academic_year: str | None = Query(None),
    semester_code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    from app.services.capability_resolution import CapabilityResolutionService
    sid = _semester_id(db, semester_id)
    suffix = Path(file.filename or "history.xlsx").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        _copy_upload_limited(file, tmp_path)
    try:
        return CapabilityResolutionService.learn_from_historical_assignment_file(
            db=db,
            file_path=tmp_path,
            semester_id=sid,
            sheet_name=sheet_name,
            academic_year=academic_year,
            semester_code=semester_code,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/semesters/{semester_id}/capabilities")
def list_semester_capabilities(
    semester_id: int,
    course_id: int | None = Query(None),
    lecturer_id: int | None = Query(None),
    source: str | None = Query(None),
    confirmed: bool | None = Query(None),
    allowed: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    from app.services.capability_resolution import CapabilityResolutionService
    sid = _semester_id(db, semester_id)
    return CapabilityResolutionService.list_capabilities(
        db,
        semester_id=sid,
        course_id=course_id,
        lecturer_id=lecturer_id,
        source=source,
        confirmed=confirmed,
        allowed=allowed,
    )


@router.post("/semesters/{semester_id}/capabilities/bulk-confirm")
def bulk_confirm_capabilities(
    semester_id: int,
    payload: CapabilityBulkConfirmRequest,
    db: Session = Depends(get_db),
):
    from app.services.capability_resolution import CapabilityResolutionService
    sid = _semester_id(db, semester_id)
    return CapabilityResolutionService.bulk_confirm_capabilities(
        db=db,
        semester_id=sid,
        capability_ids=payload.capability_ids,
        course_ids=payload.course_ids,
    )


@router.put("/capabilities/{capability_id}")
def update_capability(
    capability_id: int,
    payload: CapabilityUpdateRequest,
    db: Session = Depends(get_db),
):
    from app.services.capability_resolution import CapabilityResolutionService
    try:
        return CapabilityResolutionService.update_capability(
            db=db,
            capability_id=capability_id,
            allowed=payload.allowed,
            confirmed=payload.confirmed,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/departments")
def list_departments(db: Session = Depends(get_db)):
    from app.models.entities import Department
    depts = db.scalars(select(Department).order_by(Department.id)).all()
    return [{"id": d.id, "name": d.name, "code": d.code, "description": d.description} for d in depts]


@router.post("/departments")
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)):
    from app.models.entities import Department, DepartmentProfile
    existing = db.scalar(select(Department).where(or_(Department.name == payload.name, Department.code == payload.code)))
    if existing:
        raise HTTPException(400, "Phòng ban / bộ môn với tên hoặc mã này đã tồn tại.")
    dept = Department(name=payload.name, code=payload.code, description=payload.description)
    db.add(dept)
    db.flush()
    profile = DepartmentProfile(
        department_id=dept.id,
        allow_provisional_capability=False,
        course_capability_mode="STRICT",
        policy_config={},
    )
    db.add(profile)
    db.commit()
    db.refresh(dept)
    return {"id": dept.id, "name": dept.name, "code": dept.code, "description": dept.description}


@router.get("/departments/{department_id}/policy")
def get_department_policy(department_id: int, db: Session = Depends(get_db)):
    from app.models.entities import Department, DepartmentProfile
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy bộ môn.")
    profile = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == department_id))
    if not profile:
        profile = DepartmentProfile(
            department_id=department_id,
            allow_provisional_capability=False,
            course_capability_mode="STRICT",
            policy_config={},
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return {
        "department_id": department_id,
        "department_name": dept.name,
        "department_code": dept.code,
        "allow_provisional_capability": profile.allow_provisional_capability,
        "course_capability_mode": profile.course_capability_mode,
        "policy_config": profile.policy_config or {},
    }


@router.put("/departments/{department_id}/policy")
def update_department_policy(department_id: int, payload: DepartmentPolicyUpdate, db: Session = Depends(get_db)):
    from app.models.entities import Department, DepartmentProfile
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy bộ môn.")
    profile = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == department_id))
    if not profile:
        profile = DepartmentProfile(department_id=department_id)
        db.add(profile)
    if payload.allow_provisional_capability is not None:
        profile.allow_provisional_capability = payload.allow_provisional_capability
    if payload.course_capability_mode is not None:
        profile.course_capability_mode = payload.course_capability_mode
    if payload.policy_config is not None:
        profile.policy_config = payload.policy_config
    db.commit()
    return {
        "department_id": department_id,
        "department_name": dept.name,
        "department_code": dept.code,
        "allow_provisional_capability": profile.allow_provisional_capability,
        "course_capability_mode": profile.course_capability_mode,
        "policy_config": profile.policy_config or {},
    }

