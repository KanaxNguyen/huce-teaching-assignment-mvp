from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.exporters.excel import export_latest
from app.models.entities import (
    Assignment,
    ClassSection,
    Constraint,
    Lecturer,
    Seminar,
    ValidationIssue,
)
from app.optimization.solver import solve
from app.schemas.api import ConstraintCreate, ImportResponse, MergedDecision, OptimizationRequest
from app.services.importer import dashboard, import_files

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "HUCE Teaching Assignment API"}


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


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard(db)


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


@router.post("/optimization/run")
def run_optimization(payload: OptimizationRequest, db: Session = Depends(get_db)) -> dict:
    try:
        run = solve(db, payload.time_limit_seconds, payload.confirm_merged_suggestions)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"run_id": run.id, "status": run.status, "score": run.score, "summary": run.summary}


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
