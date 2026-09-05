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


class TemplateMappingUpdate(BaseModel):
    mappings: dict[str, Any]
    missing_fields: list[str] = Field(default_factory=list)


class OptimizationRequest(BaseModel):
    time_limit_seconds: int = Field(default=20, ge=1, le=120)
    confirm_merged_suggestions: bool = False


class MergedDecision(BaseModel):
    merged_group_id: str
    confirmed: bool


class ImportResponse(BaseModel):
    batch_id: int
    files: list[str]
    summary: dict[str, Any]
    unmatched_lecturers: list[str]
    serious_errors: int
    preview: list[dict[str, Any]]
