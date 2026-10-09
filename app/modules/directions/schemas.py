from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.directions.model import (
    ActionRecommendation,
    DirectionStatus,
    HumanApprovalStatus,
)


# ---------------------------------------------------------------------------
# Direction Version
# ---------------------------------------------------------------------------


class DirectionCreate(BaseModel):
    version_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=200)
    visual_style: str = Field(default="")
    lighting_mood: str = Field(default="")
    change_note: str = Field(default="")
    status: DirectionStatus = DirectionStatus.draft


class DirectionOut(BaseModel):
    id: str
    project_id: str
    version_number: int
    title: str
    visual_style: str
    lighting_mood: str
    change_note: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DirectionList(BaseModel):
    items: list[DirectionOut]
    total: int


# ---------------------------------------------------------------------------
# Direction Comparison
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    base_direction_id: str
    target_direction_id: str


class FieldDelta(BaseModel):
    base: str
    target: str


class CompareOut(BaseModel):
    style_delta: FieldDelta | None
    lighting_delta: FieldDelta | None
    summary: str


# ---------------------------------------------------------------------------
# Impact Analysis
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    target_direction_id: str


class ShotImpactResult(BaseModel):
    shot_id: str
    action: Literal["retain", "adapt", "regenerate", "needs_review"]
    reason: str
    confidence: float
    affected_requirements: list[str] = Field(default_factory=list)


class AnalyzeOut(BaseModel):
    results: list[ShotImpactResult]


# ---------------------------------------------------------------------------
# Shot Review / Approval
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    direction_version_id: str
    approved_action: ActionRecommendation
    note: str = Field(default="")
    prompt: str = Field(default="")
    impact_reason: str = Field(default="")


class ShotVersionOut(BaseModel):
    id: str
    shot_id: str
    version_number: int
    direction_version_id: str
    prompt: str
    action_recommendation: str | None
    human_approval_status: str
    approved_action: str | None
    impact_reason: str
    confidence_score: float | None
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Storyboard
# ---------------------------------------------------------------------------


class StoryboardShotEntry(BaseModel):
    shot_id: str
    sequence_order: int
    title: str
    shot_status: str
    current_version_id: str | None
    current_version_number: int | None
    approved_action: str | None
    human_approval_status: str | None
    asset_uri: str | None
    asset_type: str | None


class StoryboardOut(BaseModel):
    project_id: str
    shots: list[StoryboardShotEntry]
    total: int
