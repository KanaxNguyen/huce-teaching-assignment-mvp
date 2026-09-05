from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.exporters.excel import export_latest
from app.models.entities import (
    Assignment,
    ClassSection,
    ClassSession,
    Constraint,
    Lecturer,
    OutputTemplateProfile,
    OptimizationRun,
    Semester,
    Seminar,
    ValidationIssue,
)
from app.optimization.solver import solve
from app.parsers.preferences import describe_preference
from app.schemas.api import (
    ConstraintCreate,
    ConstraintUpdate,
    ImportResponse,
    AliasResolution,
    MergedDecision,
    OptimizationRequest,
    SemesterCreate,
    SeminarCreate,
    TemplateMappingUpdate,
)
from app.services.importer import dashboard, import_files
from app.services.manual_assignment import apply_manual_assignment, check_assignment_change
from app.services.template_detector import detect_output_template

router = APIRouter(prefix="/api/v1")

def _semester_id(db: Session, requested: int | None) -> int:
    semester = db.get(Semester, requested) if requested is not None else db.scalar(
        select(Semester).where(Semester.is_active.is_(True)).order_by(Semester.id.desc())
    )
    if not semester:
        raise HTTPException(422, "Cần chọn kỳ học.")
    return semester.id


def _save_typed_upload(item: UploadFile, directory: Path) -> Path:
    suffix = Path(item.filename or "").suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise HTTPException(415, f"Định dạng không hỗ trợ: {suffix}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / Path(item.filename or f"upload{suffix}").name
    with path.open("wb") as handle:
        shutil.copyfileobj(item.file, handle)
    return path


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "HUCE Teaching Assignment API"}


@router.get("/semesters")
def get_semesters(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
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
    item = Semester(
        name=payload.name.strip(),
        department_name=payload.department_name.strip(),
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
    path = _save_typed_upload(template_file, settings.resolve(settings.upload_dir) / "template")
    result = detect_output_template(path)
    profile = OutputTemplateProfile(
        semester_id=_semester_id(db, semester_id),
        # The profile is executable data, not merely a preview.  Keep the
        # exact saved upload so an export can copy that workbook later.
        source_file=str(path.resolve()),
        source_sheet=result["source_sheet"],
        header_row=result["header_row"],
        mappings=result["mappings"],
        missing_fields=result["missing_fields"],
        preview=result["preview"],
    )
    db.add(profile)
    db.commit()
    result["profile_id"] = profile.id
    return result


@router.get("/templates/latest")
def get_latest_template(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict | None:
    sid = _semester_id(db, semester_id)
    profile = db.scalars(
        select(OutputTemplateProfile).where(OutputTemplateProfile.semester_id == sid).order_by(OutputTemplateProfile.id.desc()).limit(1)
    ).first()
    if not profile:
        return None
    source_path = Path(profile.source_file)
    if not source_path.exists():
        # Compatibility with profiles created before source_file was stored
        # as an absolute upload path.
        source_path = settings.resolve(settings.upload_dir) / "template" / Path(profile.source_file).name
    if source_path.exists():
        result = detect_output_template(source_path)
    else:
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


@router.post("/imports/local", response_model=ImportResponse)
def import_local(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    source = settings.resolve(settings.source_dir)
    paths = sorted((*source.glob("*.xls"), *source.glob("*.xlsx")))
    try:
        return import_files(db, paths, semester_id=_semester_id(db, semester_id))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/imports/upload", response_model=ImportResponse)
def upload(files: list[UploadFile] = File(...), semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    upload_dir = settings.resolve(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in files:
        suffix = Path(item.filename or "").suffix.lower()
        if suffix not in {".xls", ".xlsx"}:
            raise HTTPException(415, f"Định dạng không hỗ trợ: {suffix}")
        path = upload_dir / Path(item.filename or f"upload{suffix}").name
        with path.open("wb") as handle:
            shutil.copyfileobj(item.file, handle)
        paths.append(path)
    try:
        return import_files(db, paths, semester_id=_semester_id(db, semester_id))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/imports/upload-pair", response_model=ImportResponse)
def upload_pair(
    schedule_file: UploadFile = File(...),
    preference_file: UploadFile = File(...),
    semester_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    upload_dir = settings.resolve(settings.upload_dir)
    schedule_path = _save_typed_upload(schedule_file, upload_dir / "schedule")
    preference_path = _save_typed_upload(preference_file, upload_dir / "preference")
    try:
        return import_files(
            db,
            [schedule_path, preference_path],
            schedule_paths=[schedule_path],
            preference_paths=[preference_path],
            semester_id=_semester_id(db, semester_id),
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/dashboard")
def get_dashboard(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    return dashboard(db, _semester_id(db, semester_id))


@router.get("/lecturers")
def get_lecturers(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "code": item.code,
            "name": item.canonical_name,
            "aliases": item.aliases,
            "confirmed": item.confirmed,
            "max_credits": item.max_credits,
        }
        for item in db.scalars(select(Lecturer).order_by(Lecturer.canonical_name)).all()
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
    aliases = {item.strip() for item in (lecturer.aliases or []) if item.strip()}
    aliases.add(alias)
    lecturer.aliases = sorted(aliases)
    for issue in db.scalars(select(ValidationIssue).where(
        ValidationIssue.semester_id == _semester_id(db, semester_id),
        ValidationIssue.code == "LECTURER_IDENTITY_AMBIGUOUS",
        ValidationIssue.raw_value.contains(alias),
    )).all():
        db.delete(issue)
    db.commit()
    return {"lecturer_id": lecturer.id, "aliases": lecturer.aliases, "resolved": True}


@router.get("/readiness")
def get_readiness(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    sid = _semester_id(db, semester_id)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id == sid)).all()
    course_ids = {item.course_id for item in classes}
    capability_rows = db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.course_id.in_(course_ids))).all() if course_ids else []
    capable_courses = {item.course_id for item in capability_rows if item.allowed and item.confirmed}
    issues = db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == sid)).all()
    relevant_ids = {item.assigned_lecturer_id for item in classes if item.assigned_lecturer_id}
    relevant_ids.update(item.lecturer_id for item in db.scalars(select(Constraint).where(Constraint.semester_id == sid)).all() if item.lecturer_id)
    relevant_ids.update(item.lecturer_id for item in capability_rows)
    lecturers = db.scalars(select(Lecturer).where(Lecturer.id.in_(relevant_ids))).all() if relevant_ids else []
    latest = db.scalar(select(OptimizationRun).where(OptimizationRun.semester_id == sid).order_by(OptimizationRun.id.desc()))
    warnings = []
    for issue in issues:
        if issue.code in {"LECTURER_IDENTITY_AMBIGUOUS", "PARTIAL_MERGE_CANDIDATE"}:
            warnings.append({"code": issue.code, "message": issue.message})
    missing_rooms = sum(1 for item in classes for session in item.sessions if not session.room.strip())
    if missing_rooms:
        warnings.append({"code": "MISSING_ROOM", "message": f"{missing_rooms} meeting chưa có phòng; mặc định không ghép lớp."})
    if latest and (latest.summary or {}).get("code"):
        warnings.append({"code": latest.summary["code"], "message": "Solver gần nhất đang có điều kiện blocking cần rà soát."})
    return {
        "ready": not any(item["code"] in {"LECTURER_IDENTITY_AMBIGUOUS", "PARTIAL_MERGE_CANDIDATE", "LOCKED_ASSIGNMENT_CONFLICT"} for item in warnings),
        "lecturers": {"total": len(lecturers), "resolved": sum(item.confirmed for item in lecturers), "need_review": sum(1 for issue in issues if issue.code == "LECTURER_IDENTITY_AMBIGUOUS")},
        "teaching_groups": len(classes),
        "meetings": sum(len(item.sessions) for item in classes),
        "valid_meetings": all(item.sessions for item in classes),
        "groups_without_capability": sum(item.course_id not in capable_courses for item in classes),
        "warnings": warnings,
    }


@router.get("/workload")
def get_workload(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    sid = _semester_id(db, semester_id)
    classes = db.scalars(select(ClassSection).options(selectinload(ClassSection.sessions)).where(ClassSection.semester_id == sid)).all()
    course_ids = {item.course_id for item in classes}
    lecturer_ids = {item.assigned_lecturer_id for item in classes if item.assigned_lecturer_id}
    if course_ids:
        lecturer_ids.update(
            item.lecturer_id
            for item in db.scalars(select(LecturerCourseCapability).where(LecturerCourseCapability.course_id.in_(course_ids))).all()
        )
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
def get_classes(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(
        select(ClassSection)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
        .where(ClassSection.semester_id == _semester_id(db, semester_id)).order_by(ClassSection.id)
    ).all()
    return [
        {
            "id": item.id,
            "course_id": item.course_id,
            "course_code": item.course.code,
            "course_name": item.course.name,
            "class_code": item.class_code,
            "credits": item.credits,
            "merged_group_id": item.merged_group_id,
            "merged_confirmed": item.merged_confirmed,
            "merge_status": item.merge_status,
            "locked_assignment": item.locked_assignment,
            "assignment_source": item.assignment_source,
            "lecturer_id": item.assigned_lecturer_id,
            "lecturer": item.assigned_lecturer.canonical_name if item.assigned_lecturer else None,
            "sessions": [
                {
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
        }
        for item in items
    ]

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
    result = apply_manual_assignment(db, semester_id, class_id, int(payload["lecturer_id"]), bool(payload.get("lock", False)))
    if not result["valid"]: raise HTTPException(422, result)
    return result

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


def _meeting_signature(session: ClassSession) -> tuple:
    return (session.weekday, session.start_period, session.end_period, session.room.casefold(), tuple(session.active_weeks))


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
            "classes": [{"id": item.id, "class_code": item.class_code, "course": item.course.name} for item in items],
            "matched_meetings": len(signatures), "different_meetings": 0,
            "meeting_details": [
                {"weekday": session.weekday, "periods": f"{session.start_period}-{session.end_period}", "room": session.room, "weeks": session.active_weeks}
                for session in items[0].sessions
            ],
        })
    for index, left in enumerate(classes):
        left_signatures = {_meeting_signature(item) for item in left.sessions if item.room.strip()}
        if not left_signatures:
            continue
        for right in classes[index + 1:]:
            if left.course_id != right.course_id:
                continue
            right_signatures = {_meeting_signature(item) for item in right.sessions if item.room.strip()}
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
        run = solve(db, payload.time_limit_seconds, payload.confirm_merged_suggestions, _semester_id(db, semester_id))
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
    previous = db.scalar(select(OptimizationRun).where(
        OptimizationRun.semester_id == semester_id, OptimizationRun.id < run.id,
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
def get_assignments(semester_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[dict]:
    sid = _semester_id(db, semester_id)
    latest = db.scalar(select(Assignment.run_id).where(Assignment.semester_id == sid).order_by(Assignment.run_id.desc()).limit(1))
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
            "raw_value": issue.raw_value,
        }
        for issue in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == _semester_id(db, semester_id)).order_by(ValidationIssue.id)).all()
    ]

@router.get("/problems")
def get_problems(semester_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    _semester_id(db, semester_id)
    problems = {}
    def add(code, severity, entity_type, entity_id, message, reasons=None, lecturer_id=None, constraints=None):
        key = (code, entity_type, str(entity_id))
        problems.setdefault(key, {"code": code, "severity": severity, "entity_type": entity_type, "entity_id": str(entity_id), "lecturer_id": lecturer_id, "message": message, "reasons": reasons or [], "related_constraints": constraints or [], "resolvable": True})
    for issue in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == semester_id)):
        add(issue.code, "critical" if issue.severity == "error" else "warning", "validation_issue", issue.id, issue.message)
    run = db.scalar(select(OptimizationRun).where(OptimizationRun.semester_id == semester_id).order_by(OptimizationRun.id.desc()))
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
            reasons = item.get("reasons", [])
            primary = reasons[0].get("reason", "NO_ELIGIBLE_LECTURER") if reasons else "NO_ELIGIBLE_LECTURER"
            add("UNASSIGNED", "warning", "class_section", item["class_id"], "TeachingGroup chưa được phân công.", reasons)
            add(primary, "warning", "class_section", item["class_id"], primary, reasons)
        for item in summary.get("unsupported_constraints", []):
            add("UNSUPPORTED_CONSTRAINT_TYPE", "warning", "constraint", item, f"Constraint không được hỗ trợ: {item}")
        for item in summary.get("invalid_constraints", []):
            add("UNSUPPORTED_CONSTRAINT_TYPE", "warning", "constraint", item, "Constraint có target không hợp lệ.")
    return list(problems.values())


@router.get("/exports/latest")
def download_export(
    semester_id: int | None = Query(None),
    mode: str = Query("draft", pattern="^(draft|final)$"),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        path = export_latest(db, settings.resolve(settings.export_dir), _semester_id(db, semester_id), mode=mode)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
