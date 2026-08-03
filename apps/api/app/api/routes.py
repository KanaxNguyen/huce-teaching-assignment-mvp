from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.exporters.excel import export_latest
from app.exporters.integrations import export_csv_bytes, export_ics_bytes, export_json_bytes
from app.models.entities import (
    Assignment,
    ClassSection,
    Constraint,
    ImportBatch,
    Lecturer,
    OptimizationRun,
    Seminar,
    ValidationIssue,
)
from app.optimization.solver import solve
from app.schemas.api import (
    AppSettingUpdate,
    ConstraintCreate,
    ConstraintUpdate,
    ImportResponse,
    MergedDecision,
    OptimizationRequest,
    SeminarUpdate,
)
from app.services.importer import dashboard, import_files
from app.services.settings import get_app_settings, settings_payload

router = APIRouter(prefix="/api/v1")


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


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return settings_payload(get_app_settings(db))


@router.put("/settings")
def update_settings(payload: AppSettingUpdate, db: Session = Depends(get_db)) -> dict:
    item = get_app_settings(db)
    start = payload.semester_start
    end = payload.semester_end
    if start and end and start > end:
        raise HTTPException(422, "Ngày bắt đầu học kỳ phải trước ngày kết thúc.")
    item.academic_year = payload.academic_year.strip()
    item.semester = payload.semester
    item.semester_start = start
    item.semester_end = end
    item.institution = payload.institution.strip()
    item.department = payload.department.strip()
    item.calendar_name = payload.calendar_name.strip()
    item.timezone_name = payload.timezone_name.strip()
    item.primary_lecturer = payload.primary_lecturer.strip() if payload.primary_lecturer else None
    db.commit()
    db.refresh(item)
    return settings_payload(item)


@router.post("/imports/local", response_model=ImportResponse)
def import_local(db: Session = Depends(get_db)) -> dict:
    source = settings.resolve(settings.source_dir)
    paths = sorted((*source.glob("*.xls"), *source.glob("*.xlsx")))
    try:
        return import_files(db, paths)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/imports/upload", response_model=ImportResponse)
def upload(files: list[UploadFile] = File(...), db: Session = Depends(get_db)) -> dict:
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
        return import_files(db, paths)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/imports/upload-pair", response_model=ImportResponse)
def upload_pair(
    schedule_file: UploadFile = File(...),
    preference_file: UploadFile = File(...),
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
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/imports/upload-bundle", response_model=ImportResponse)
def upload_bundle(
    schedule_file: UploadFile = File(...),
    preference_file: UploadFile = File(...),
    template_file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    upload_dir = settings.resolve(settings.upload_dir)
    schedule_path = _save_typed_upload(schedule_file, upload_dir / "schedule")
    preference_path = _save_typed_upload(preference_file, upload_dir / "preference")
    paths = [schedule_path, preference_path]
    template_path = None
    if template_file:
        template_path = _save_typed_upload(template_file, upload_dir / "template")
        paths.append(template_path)
    try:
        return import_files(
            db,
            paths,
            schedule_paths=[schedule_path],
            preference_paths=[preference_path],
            template_paths=[template_path] if template_path else [],
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard(db)


@router.get("/imports/latest")
def get_latest_import(db: Session = Depends(get_db)) -> dict:
    item = db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())).first()
    if not item:
        return {"batch": None}
    return {
        "batch": {
            "id": item.id,
            "created_at": item.created_at,
            "source_files": item.source_files,
            "summary": item.summary,
        }
    }


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


@router.get("/classes")
def get_classes(db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(
        select(ClassSection)
        .options(
            selectinload(ClassSection.course),
            selectinload(ClassSection.sessions),
            selectinload(ClassSection.assigned_lecturer),
        )
        .order_by(ClassSection.id)
    ).all()
    return [
        {
            "id": item.id,
            "course_code": item.course.code,
            "course_name": item.course.name,
            "class_code": item.class_code,
            "credits": item.credits,
            "merged_group_id": item.merged_group_id,
            "merged_confirmed": item.merged_confirmed,
            "locked_assignment": item.locked_assignment,
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


@router.patch("/merged-groups")
def decide_merged_group(payload: MergedDecision, db: Session = Depends(get_db)) -> dict:
    items = db.scalars(
        select(ClassSection).where(ClassSection.merged_group_id == payload.merged_group_id)
    ).all()
    if not items:
        raise HTTPException(404, "Không tìm thấy nhóm ghép.")
    for item in items:
        item.merged_confirmed = payload.confirmed
    db.commit()
    return {"merged_group_id": payload.merged_group_id, "confirmed": payload.confirmed, "classes": len(items)}


@router.get("/constraints")
def get_constraints(db: Session = Depends(get_db)) -> list[dict]:
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
            "raw_text": item.raw_text,
            "confirmed": item.confirmed,
            "active": item.active,
        }
        for item in db.scalars(
            select(Constraint).options(selectinload(Constraint.lecturer)).order_by(Constraint.id)
        ).all()
    ]


@router.post("/constraints")
def create_constraint(payload: ConstraintCreate, db: Session = Depends(get_db)) -> dict:
    item = Constraint(**payload.model_dump())
    db.add(item)
    db.commit()
    return {"id": item.id, "created": True}


@router.patch("/constraints/{constraint_id}")
def update_constraint(
    constraint_id: int,
    payload: ConstraintUpdate,
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(Constraint, constraint_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy ràng buộc.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(item, field, value)
    if item.hardness == "hard":
        item.weight = 1
    db.commit()
    return {"id": item.id, "updated": True}


@router.delete("/constraints/{constraint_id}")
def delete_constraint(constraint_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(Constraint, constraint_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy ràng buộc.")
    db.delete(item)
    db.commit()
    return {"id": constraint_id, "deleted": True}


@router.post("/seminars")
def create_seminar(payload: dict, db: Session = Depends(get_db)) -> dict:
    item = Seminar(
        name=payload["name"],
        chair_name=payload.get("chair_name", ""),
        members=payload.get("members", []),
        alternatives=payload.get("alternatives", []),
        weight=float(payload.get("weight", 0.8)),
        hardness=payload.get("hardness", "soft"),
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "created": True}


@router.get("/seminars")
def get_seminars(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "chair_name": item.chair_name,
            "members": item.members,
            "alternatives": item.alternatives,
            "weight": item.weight,
            "hardness": item.hardness,
        }
        for item in db.scalars(select(Seminar).order_by(Seminar.id)).all()
    ]


@router.patch("/seminars/{seminar_id}")
def update_seminar(seminar_id: int, payload: SeminarUpdate, db: Session = Depends(get_db)) -> dict:
    item = db.get(Seminar, seminar_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy seminar.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    if item.hardness == "hard":
        item.weight = 1
    db.commit()
    return {"id": item.id, "updated": True}


@router.post("/optimization/run")
def run_optimization(payload: OptimizationRequest, db: Session = Depends(get_db)) -> dict:
    try:
        run = solve(db, payload.time_limit_seconds, payload.confirm_merged_suggestions)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"run_id": run.id, "status": run.status, "score": run.score, "summary": run.summary}


@router.get("/optimization/runs")
def get_optimization_runs(limit: int = 10, db: Session = Depends(get_db)) -> list[dict]:
    runs = db.scalars(
        select(OptimizationRun).order_by(OptimizationRun.id.desc()).limit(min(max(limit, 1), 50))
    ).all()
    return [
        {
            "id": item.id,
            "created_at": item.created_at,
            "status": item.status,
            "score": item.score,
            "summary": item.summary,
        }
        for item in runs
    ]


@router.get("/assignments")
def get_assignments(db: Session = Depends(get_db)) -> list[dict]:
    latest = db.scalar(select(Assignment.run_id).order_by(Assignment.run_id.desc()).limit(1))
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
def get_conflicts(db: Session = Depends(get_db)) -> list[dict]:
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
        }
        for issue in db.scalars(select(ValidationIssue).order_by(ValidationIssue.id)).all()
    ]


@router.get("/exports/latest")
def download_export(db: Session = Depends(get_db)) -> FileResponse:
    try:
        path = export_latest(db, settings.resolve(settings.export_dir))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/exports/calendar.ics")
def download_calendar(lecturer: str | None = None, db: Session = Depends(get_db)) -> Response:
    try:
        content = export_ics_bytes(db, lecturer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    app_settings = get_app_settings(db)
    filename = f"HUCE-TKB-HK{app_settings.semester}-{app_settings.academic_year}.ics"
    return Response(
        content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/assignments.csv")
def download_csv(lecturer: str | None = None, db: Session = Depends(get_db)) -> Response:
    try:
        content = export_csv_bytes(db, lecturer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    app_settings = get_app_settings(db)
    filename = f"HUCE-Phan-Cong-HK{app_settings.semester}-{app_settings.academic_year}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/schedule.json")
def download_json(lecturer: str | None = None, db: Session = Depends(get_db)) -> Response:
    try:
        content = export_json_bytes(db, lecturer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    app_settings = get_app_settings(db)
    filename = f"HUCE-TKB-HK{app_settings.semester}-{app_settings.academic_year}.json"
    return Response(
        content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
