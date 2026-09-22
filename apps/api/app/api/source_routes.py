from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.entities import Semester, SourceVersion
from app.api.routes import _temporary_typed_upload, WORKBOOK_ERRORS
from app.services.source_authority import (SourceError, stage_source, source_payload,
    preview_activation, activate_source, active_issues, resolve_issue)

router = APIRouter(prefix='/api/v1/sources')
Role = Literal['CURRENT_SCHEDULE', 'PREFERENCE', 'HISTORICAL', 'OUTPUT_TEMPLATE', 'REFERENCE_MATRIX']


class Activation(BaseModel):
    source_type: Role
    confirmed: bool = False
    preview_token: str = ''


class Resolution(BaseModel):
    action: Literal['NORMALIZE_SINGLE', 'CORRECT_INTERPRETATION', 'DEFER_SPECIAL', 'ACKNOWLEDGE_STALE']
    lecturer_id: int | None = None
    note: str
    actor: str


def require_semester(db, sid):
    semester = db.get(Semester, sid)
    if not semester: raise HTTPException(404, 'Không tìm thấy kỳ học.')
    return semester


@router.get('')
def sources(semester_id: int, db: Session = Depends(get_db)):
    semester = require_semester(db, semester_id)
    return {'sources': [source_payload(s, semester) for s in db.scalars(select(SourceVersion).where(SourceVersion.semester_id == semester_id).order_by(SourceVersion.id.desc()))],
            'active_schedule_source_id': semester.active_schedule_source_id,
            'active_preference_source_id': semester.active_preference_source_id,
            'source_revision': semester.source_revision,
            'legacy_unverified': semester.active_schedule_source_id is None,
            'issues': [{'id': i.id, 'code': i.code, 'message': i.message, 'details': i.details,
                        'resolution_status': i.resolution_status} for i in active_issues(db, semester_id)
                       if i.code in {'MULTI_LECTURER_REVIEW', 'SPLIT_ASSIGNMENT_REQUIRES_SEGMENT_SUPPORT', 'SOURCE_CHANGED_REVIEW_REQUIRED'}]}


@router.post('/upload')
def upload_source(file: UploadFile = File(...), source_type: Role = Query(...), semester_id: int = Query(...), parent_version_id: int | None = None, db: Session = Depends(get_db)):
    semester = require_semester(db, semester_id)
    try:
        with _temporary_typed_upload(file) as path:
            source = stage_source(db, path, semester_id, source_type, parent_id=parent_version_id)
            db.commit()
            return source_payload(source, semester)
    except SourceError as error:
        db.rollback(); raise HTTPException(422, error.detail) from error
    except (ValueError, *WORKBOOK_ERRORS) as error:
        db.rollback(); raise HTTPException(422, 'Không thể đọc nguồn; chưa thay đổi nguồn đang hoạt động.') from error


@router.post('/{source_id}/preview')
def preview(source_id: int, payload: Activation, semester_id: int, db: Session = Depends(get_db)):
    require_semester(db, semester_id)
    try: return preview_activation(db, semester_id, source_id, payload.source_type)
    except SourceError as error: raise HTTPException(422, error.detail) from error
    except (ValueError, *WORKBOOK_ERRORS) as error: raise HTTPException(422, str(error)) from error


@router.post('/{source_id}/activate')
def activate(source_id: int, payload: Activation, semester_id: int, db: Session = Depends(get_db)):
    require_semester(db, semester_id)
    try: return activate_source(db, semester_id, source_id, payload.source_type, confirmed=payload.confirmed, preview_token=payload.preview_token)
    except SourceError as error: raise HTTPException(422, error.detail) from error
    except (ValueError, *WORKBOOK_ERRORS) as error:
        db.rollback(); raise HTTPException(422, str(error)) from error


@router.post('/reviews/{issue_id}/resolve')
def resolve(issue_id: int, payload: Resolution, semester_id: int, db: Session = Depends(get_db)):
    require_semester(db, semester_id)
    try: return resolve_issue(db, semester_id, issue_id, **payload.model_dump())
    except SourceError as error:
        db.rollback(); raise HTTPException(422, error.detail) from error
