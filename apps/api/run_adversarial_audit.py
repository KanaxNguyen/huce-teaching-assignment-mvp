import asyncio
from pathlib import Path
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, engine, Base
from app.api.routes import import_schedule_file, import_preference_file, apply_preference_drafts
from app.optimization.solver import solve
from app.models.entities import Semester, Lecturer, ClassSection, Constraint, NormalizedPreferenceDraft
from fastapi import UploadFile
from typing import Any

def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    semester = Semester(name="HK1 2026-2027", department_name="Toán", start_date="2026-08-15", end_date="2026-12-31", head_name="Admin")
    db.add(semester)
    db.commit()
    return db, semester.id

# We will write the full script step by step.
