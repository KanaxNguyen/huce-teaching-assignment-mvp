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
