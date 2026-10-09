import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def now():
    return datetime.now(timezone.utc)


def new_id(prefix):
    return prefix + "_" + uuid.uuid4().hex


class Moodboard(Base):
    __tablename__ = "moodboards"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mb"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    context: Mapped[str] = mapped_column(Text, default="")
    intended_use: Mapped[str] = mapped_column(String(20), default="general")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_approved_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MoodboardSource(Base):
    __tablename__ = "moodboard_sources"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    moodboard_id: Mapped[str] = mapped_column(ForeignKey("moodboards.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(100))
    analysis_key: Mapped[str] = mapped_column(String(100))
    checksum: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(30))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    roles: Mapped[list] = mapped_column(JSON, default=lambda: ["overall"])
    roles_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    sequence_order: Mapped[int] = mapped_column(Integer, default=1)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractionVersion(Base):
    __tablename__ = "moodboard_versions"
    __table_args__ = (UniqueConstraint("moodboard_id", "version_number"),
                      UniqueConstraint("moodboard_id", "idempotency_key"))
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ver"))
    moodboard_id: Mapped[str] = mapped_column(ForeignKey("moodboards.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    based_on_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(20), default="draft")
    job_status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    per_source: Mapped[dict] = mapped_column(JSON, default=dict)
    original_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    conflict_resolutions: Mapped[dict] = mapped_column(JSON, default=dict)
    instructions: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewEvent(Base):
    __tablename__ = "moodboard_review_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt"))
    version_id: Mapped[str] = mapped_column(ForeignKey("moodboard_versions.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(30), default="local_user")
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MoodboardExport(Base):
    __tablename__ = "moodboard_exports"
    __table_args__ = (UniqueConstraint("version_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("exp"))
    version_id: Mapped[str] = mapped_column(ForeignKey("moodboard_versions.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(2))
    template_version: Mapped[str] = mapped_column(String(10), default="1.0")
    status: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
