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
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Semester(Base):
    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    department_name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    head_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutputTemplateProfile(Base):
    __tablename__ = "output_template_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    source_file: Mapped[str] = mapped_column(String(300))
    source_sheet: Mapped[str] = mapped_column(String(100))
    header_row: Mapped[int] = mapped_column(Integer)
    mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class LecturerCourseCapability(Base):
    __tablename__ = "lecturer_course_capabilities"
    __table_args__ = (UniqueConstraint("lecturer_id", "course_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ClassSection(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("semester_id", "course_id", "class_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    class_code: Mapped[str] = mapped_column(String(100))
    credits: Mapped[float] = mapped_column(Float, default=0)
    merged_group_id: Mapped[str | None] = mapped_column(String(100))
    merged_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # candidate | confirmed | rejected.  `merged_confirmed` remains for v1
    # compatibility with existing solver and exported data.
    merge_status: Mapped[str] = mapped_column(String(20), default="single")
    locked_assignment: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"), nullable=True)
    assignment_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
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


class NormalizedPreferenceDraft(Base):
    """Reviewable parser output. Solver-visible constraints are created only on apply."""

    __tablename__ = "normalized_preference_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"), nullable=True)
    lecturer_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lecturer_alias: Mapped[str | None] = mapped_column(String(200), nullable=True)
    draft_kind: Mapped[str] = mapped_column(String(30), default="CONSTRAINT")
    context_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    context_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    context_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    constraint_type: Mapped[str] = mapped_column(String(60))
    day_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    periods: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    hardness: Mapped[str] = mapped_column(String(10), default="soft")
    weight: Mapped[float] = mapped_column(Float, default=0.8)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    participant_codes: Mapped[list] = mapped_column(JSON, default=list)
    seminar_link: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_file: Mapped[str] = mapped_column(String(300))
    source_sheet: Mapped[str] = mapped_column(String(100))
    source_row: Mapped[int] = mapped_column(Integer)
    source_cell: Mapped[str] = mapped_column(String(60))
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="LOW")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    applied_constraint_id: Mapped[int | None] = mapped_column(ForeignKey("constraints.id"), nullable=True)
    applied_seminar_id: Mapped[int | None] = mapped_column(ForeignKey("seminars.id"), nullable=True)

    lecturer: Mapped[Lecturer | None] = relationship(foreign_keys=[lecturer_id])


class Seminar(Base):
    __tablename__ = "seminars"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    name: Mapped[str] = mapped_column(String(200))
    chair_name: Mapped[str] = mapped_column(String(200))
    members: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    weight: Mapped[float] = mapped_column(Float, default=0.8)
    hardness: Mapped[str] = mapped_column(String(10), default="soft")


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
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
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("run_id", "class_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("optimization_runs.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="SOLVER")
    penalty: Mapped[float] = mapped_column(Float, default=0)

    class_section: Mapped[ClassSection] = relationship()
    lecturer: Mapped[Lecturer] = relationship()
