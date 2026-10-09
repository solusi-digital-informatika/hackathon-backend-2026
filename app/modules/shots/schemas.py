from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.shots.model import ShotStatus


class ShotCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    sequence_order: int | None = Field(default=None, ge=1)

    @field_validator("title", mode="before")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Must not be blank")
            return stripped
        return v

    @field_validator("description", mode="before")
    @classmethod
    def description_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class ShotUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    status: ShotStatus | None = None
    sequence_order: int | None = Field(default=None, ge=1)

    @field_validator("title", mode="before")
    @classmethod
    def title_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Must not be blank")
            return stripped
        return v

    @field_validator("description", mode="before")
    @classmethod
    def description_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class ShotOut(BaseModel):
    id: str
    project_id: str
    sequence_order: int
    title: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShotList(BaseModel):
    items: list[ShotOut]
    total: int
