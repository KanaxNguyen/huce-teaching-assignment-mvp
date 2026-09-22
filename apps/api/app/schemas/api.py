from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConstraintCreate(BaseModel):
    name: str
    constraint_type: str
    hardness: Literal["hard", "soft"] = "soft"
    weight: float = Field(default=0.8, ge=0, le=1)
    lecturer_id: int | None = None
    target: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None
    confirmed: bool = True


class ConstraintUpdate(BaseModel):
    name: str | None = None
    constraint_type: str | None = None
    hardness: Literal["hard", "soft"] | None = None
    weight: float | None = Field(default=None, ge=0, le=1)
    lecturer_id: int | None = None
    target: dict[str, Any] | None = None
    raw_text: str | None = None
    confirmed: bool | None = None
    active: bool | None = None


class SemesterCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    department_name: str = Field(min_length=2, max_length=200)
    start_date: str
    end_date: str
    head_name: str = Field(min_length=2, max_length=200)
    department_id: int | None = None


class TemplateMappingUpdate(BaseModel):
    mappings: dict[str, Any]
    missing_fields: list[str] = Field(default_factory=list)


class OptimizationRequest(BaseModel):
    time_limit_seconds: int = Field(default=20, ge=1, le=120)
    confirm_merged_suggestions: bool = False


class MergedDecision(BaseModel):
    merged_group_id: str
    confirmed: bool


class MergeClassesRequest(BaseModel):
    class_ids: list[int] = Field(min_length=2)
    merged_group_id: str | None = None


class UnmergeClassesRequest(BaseModel):
    class_ids: list[int] = Field(default_factory=list)
    merged_group_id: str | None = None


class SeminarCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    chair_name: str = ""
    members: list[int] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    hardness: Literal["hard", "soft"] = "soft"
    weight: float = Field(default=0.8, ge=0, le=1)


class AliasResolution(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


class ImportResponse(BaseModel):
    batch_id: int
    files: list[str]
    summary: dict[str, Any]
    unmatched_lecturers: list[str]
    serious_errors: int
    preview: list[dict[str, Any]]


class PreferenceDraftUpdate(BaseModel):
    lecturer_id: int | None = None
    context_type: Literal["TEACHING", "SEMINAR", "MIXED"] | None = None
    constraint_type: str | None = None
    day_scope: str | None = None
    periods: list[int] | None = None
    start_date: str | None = None
    end_date: str | None = None
    hardness: Literal["hard", "soft"] | None = None
    weight: float | None = Field(default=None, ge=0, le=1)
    numeric_value: float | None = None
    raw_text: str | None = None
    seminar_link: str | None = None
    status: Literal["DRAFT", "CONFIRMED", "NEEDS_REVIEW", "REJECTED"] | None = None
    rejected_reason: str | None = None
    review_reason: str | None = None


class PreferenceDraftApply(BaseModel):
    draft_ids: list[int] = Field(min_length=1)


class ManualDraftPart(BaseModel):
    context_type: Literal["TEACHING", "SEMINAR"]
    constraint_type: str
    day_scope: str | None = None
    periods: list[int] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    hardness: Literal["hard", "soft"] = "soft"
    weight: float = Field(default=0.8, ge=0, le=1)
    numeric_value: float | None = None
    seminar_link: str | None = None
    note: str | None = None
    status: Literal["DRAFT", "CONFIRMED"] = "DRAFT"


class ManualPreferenceDraftCreate(ManualDraftPart):
    lecturer_id: int
    context_type: Literal["TEACHING", "SEMINAR", "MIXED"]
    parts: list[ManualDraftPart] = Field(default_factory=list)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    description: str | None = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None = None


class DepartmentPolicyUpdate(BaseModel):
    allow_provisional_capability: bool | None = None
    course_capability_mode: Literal["STRICT", "PERMISSIVE_WITH_PENALTY", "DEPARTMENT_ONLY"] | None = None
    policy_config: dict[str, Any] | None = None


class CapabilityBulkConfirmRequest(BaseModel):
    capability_ids: list[int] | None = None
    course_ids: list[int] | None = None


class CapabilityUpdateRequest(BaseModel):
    allowed: bool | None = None
    confirmed: bool | None = None


