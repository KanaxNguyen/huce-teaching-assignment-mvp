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


class SourceVersion(Base):
    """One immutable uploaded workbook; activation lives on Semester."""
    __tablename__ = "source_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30))
    original_filename: Mapped[str] = mapped_column(String(300))
    storage_ref: Mapped[str | None] = mapped_column(String(600), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance_status: Mapped[str] = mapped_column(String(30), default="VERIFIED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    parse_summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    profile: Mapped[DepartmentProfile | None] = relationship(back_populates="department", uselist=False)


class DepartmentProfile(Base):
    __tablename__ = "department_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), unique=True)
    allow_provisional_capability: Mapped[bool] = mapped_column(Boolean, default=False)
    course_capability_mode: Mapped[str] = mapped_column(String(30), default="STRICT")
    default_max_classes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_max_sessions_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_max_days_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    department: Mapped[Department] = relationship(back_populates="profile")


class Semester(Base):
    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    active_schedule_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id", use_alter=True, name="fk_semester_active_schedule"), nullable=True)
    active_preference_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id", use_alter=True, name="fk_semester_active_preference"), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    department_name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    head_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    department: Mapped[Department | None] = relationship(foreign_keys=[department_id])


class OutputTemplateProfile(Base):
    __tablename__ = "output_template_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    profile_type: Mapped[str] = mapped_column(String(40), default="DETAILED_ASSIGNMENT")
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    source_file: Mapped[str] = mapped_column(String(300))
    source_sheet: Mapped[str] = mapped_column(String(100))
    header_row: Mapped[int] = mapped_column(Integer)
    mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HistoricalAssignmentImport(Base):
    __tablename__ = "historical_assignment_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    source_file: Mapped[str] = mapped_column(String(300))
    source_sheet: Mapped[str] = mapped_column(String(100))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    learned_capabilities: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lecturer(Base):
    __tablename__ = "lecturers"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    max_credits: Mapped[float] = mapped_column(Float, default=24)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_sheet: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)

    department_rel: Mapped[Department | None] = relationship(foreign_keys=[department_id])


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(300))


class LecturerAlias(Base):
    __tablename__ = "lecturer_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    alias_text: Mapped[str] = mapped_column(String(300))
    normalized_alias: Mapped[str] = mapped_column(String(300), unique=True)
    source: Mapped[str] = mapped_column(String(300), default="MANUAL")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LecturerSemesterProfile(Base):
    __tablename__ = "lecturer_semester_profiles"
    __table_args__ = (UniqueConstraint("semester_id", "lecturer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    participation_status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    target_workload: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_workload: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_workload: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class HistoricalEvidence(Base):
    __tablename__ = "historical_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("output_template_profiles.id"))
    lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"), nullable=True)
    source_text: Mapped[str] = mapped_column(Text)
    lecturer_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_row: Mapped[int] = mapped_column(Integer)
    source_cell: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="NEW_LECTURER_CANDIDATE")
    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class LecturerIdentityAudit(Base):
    __tablename__ = "lecturer_identity_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    target_lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    action: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LecturerCourseCapability(Base):
    __tablename__ = "lecturer_course_capabilities"
    __table_args__ = (UniqueConstraint("lecturer_id", "course_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("lecturers.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lecturer: Mapped[Lecturer] = relationship()
    course: Mapped[Course] = relationship()
    department: Mapped[Department | None] = relationship(foreign_keys=[department_id])


class ClassSection(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("semester_id", "course_id", "class_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
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

    @property
    def resolution_status(self) -> str:
        return (self.raw_values or {}).get("resolution_status", "NEW")

    @resolution_status.setter
    def resolution_status(self, val: str):
        values = dict(self.raw_values or {})
        values["resolution_status"] = val
        self.raw_values = values
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(self, "raw_values")

    @property
    def resolution_notes(self) -> str | None:
        return (self.raw_values or {}).get("resolution_notes")

    @resolution_notes.setter
    def resolution_notes(self, val: str | None):
        values = dict(self.raw_values or {})
        values["resolution_notes"] = val
        self.raw_values = values
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(self, "raw_values")


    course: Mapped[Course] = relationship()
    assigned_lecturer: Mapped[Lecturer | None] = relationship(foreign_keys=[assigned_lecturer_id])
    sessions: Mapped[list[ClassSession]] = relationship(
        cascade="all, delete-orphan", back_populates="class_section"
    )


class ClassSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    source_rows: Mapped[list] = mapped_column(JSON, default=list)
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
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
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
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
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
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    applied_constraint_id: Mapped[int | None] = mapped_column(ForeignKey("constraints.id"), nullable=True)
    applied_seminar_id: Mapped[int | None] = mapped_column(ForeignKey("seminars.id"), nullable=True)

    lecturer: Mapped[Lecturer | None] = relationship(foreign_keys=[lecturer_id])


class Seminar(Base):
    __tablename__ = "seminars"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
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
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution_status: Mapped[str] = mapped_column(String(40), default="OPEN")
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
    schedule_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    preference_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_versions.id"), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, default=0)
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

