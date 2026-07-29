from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Lecturer(Base):
    __tablename__ = "lecturers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(200), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    max_credits: Mapped[float] = mapped_column(Float, default=24)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_sheet: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(300))


class ClassSection(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("course_id", "class_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    class_code: Mapped[str] = mapped_column(String(100))
    credits: Mapped[float] = mapped_column(Float, default=0)
    merged_group_id: Mapped[str | None] = mapped_column(String(100))
    merged_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_assignment: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"), nullable=True)
    source_file: Mapped[str] = mapped_column(String(300))
    source_sheet: Mapped[str] = mapped_column(String(100))
    source_row: Mapped[int] = mapped_column(Integer)
    raw_values: Mapped[dict] = mapped_column(JSON, default=dict)

    course: Mapped[Course] = relationship()
    assigned_lecturer: Mapped[Lecturer | None] = relationship(foreign_keys=[assigned_lecturer_id])
    sessions: Mapped[list[ClassSession]] = relationship(
        cascade="all, delete-orphan", back_populates="class_section"
    )


class ClassSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    weekday: Mapped[int] = mapped_column(Integer)
    start_period: Mapped[int] = mapped_column(Integer)
    end_period: Mapped[int] = mapped_column(Integer)
    room: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    raw_weeks: Mapped[str] = mapped_column(String(80))
    active_weeks: Mapped[list] = mapped_column(JSON, default=list)
    source_row: Mapped[int] = mapped_column(Integer)

    class_section: Mapped[ClassSection] = relationship(back_populates="sessions")


class Constraint(Base):
    __tablename__ = "constraints"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    constraint_type: Mapped[str] = mapped_column(String(50))
    hardness: Mapped[str] = mapped_column(String(10), default="soft")
    weight: Mapped[float] = mapped_column(Float, default=0.8)
    lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"), nullable=True)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_text: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    lecturer: Mapped[Lecturer | None] = relationship()


class Seminar(Base):
    __tablename__ = "seminars"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    chair_name: Mapped[str] = mapped_column(String(200))
    members: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    weight: Mapped[float] = mapped_column(Float, default=0.8)
    hardness: Mapped[str] = mapped_column(String(10), default="soft")


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    severity: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_sheet: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(100))
    raw_value: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("run_id", "class_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("optimization_runs.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    penalty: Mapped[float] = mapped_column(Float, default=0)

    class_section: Mapped[ClassSection] = relationship()
    lecturer: Mapped[Lecturer] = relationship()
