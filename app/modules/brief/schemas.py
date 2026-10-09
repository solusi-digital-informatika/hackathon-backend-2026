import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)

    @field_validator("source_name", mode="before")
    @classmethod
    def source_name_not_blank(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Must not be blank")
            return stripped
        return v

    @field_validator("content", mode="before")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Must not be blank")
            return stripped
        return v


class SourceDocumentOut(BaseModel):
    id: str
    project_id: str
    source_name: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Structured brief
# ---------------------------------------------------------------------------


class CharacterSpec(BaseModel):
    name: str
    details: str


class PropSpec(BaseModel):
    name: str
    details: str


class ProjectBriefOut(BaseModel):
    id: str
    project_id: str
    source_document_id: str | None
    objective: str
    visual_style: str
    lighting_mood: str
    characters: list[CharacterSpec]
    key_props: list[PropSpec]
    constraints: list[str]
    unresolved_questions: list[str]
    review_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, row) -> "ProjectBriefOut":
        return cls(
            id=row.id,
            project_id=row.project_id,
            source_document_id=row.source_document_id,
            objective=row.objective,
            visual_style=row.visual_style,
            lighting_mood=row.lighting_mood,
            characters=json.loads(row.characters),
            key_props=json.loads(row.key_props),
            constraints=json.loads(row.constraints),
            unresolved_questions=json.loads(row.unresolved_questions),
            review_status=row.review_status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# GET /brief response — source doc + structured extraction
# ---------------------------------------------------------------------------


class BriefOut(BaseModel):
    source_document: SourceDocumentOut
    brief: ProjectBriefOut


# ---------------------------------------------------------------------------
# PUT /brief — human update/approval
# ---------------------------------------------------------------------------


class BriefUpdate(BaseModel):
    objective: str | None = None
    visual_style: str | None = None
    lighting_mood: str | None = None
    characters: list[CharacterSpec] | None = None
    key_props: list[PropSpec] | None = None
    constraints: list[str] | None = None
    unresolved_questions: list[str] | None = None
    review_status: str | None = None

    @field_validator("review_status", mode="before")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"pending_review", "approved"}
        if v not in allowed:
            raise ValueError(f"Must be one of {sorted(allowed)}")
        return v
