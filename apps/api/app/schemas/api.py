from __future__ import annotations

from datetime import date
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


class SeminarUpdate(BaseModel):
    weight: float | None = Field(default=None, ge=0, le=1)
    hardness: Literal["hard", "soft"] | None = None


class AppSettingUpdate(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    semester: int = Field(ge=1, le=3)
    semester_start: date | None = None
    semester_end: date | None = None
    institution: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    calendar_name: str = Field(min_length=1, max_length=200)
    timezone_name: Literal["Asia/Ho_Chi_Minh"] = "Asia/Ho_Chi_Minh"
    primary_lecturer: str | None = Field(default=None, max_length=200)


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
