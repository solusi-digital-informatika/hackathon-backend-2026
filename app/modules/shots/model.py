import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    # Stable opaque ID: shot_ prefix + 8 hex chars from uuid4
    return "shot_" + uuid.uuid4().hex[:8]


class ShotStatus(str, enum.Enum):
    draft = "draft"
    in_progress = "in_progress"
    in_review = "in_review"
    approved = "approved"


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ShotStatus] = mapped_column(
        Enum(ShotStatus, name="shot_status"), nullable=False, default=ShotStatus.draft
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    @property
    def revision_summary(self):
        from sqlalchemy import select, func
        from sqlalchemy.orm import object_session
        session = object_session(self)
        head = session.get(ShotRevisionHead, self.id) if session else None
        current = session.get(ShotRevision, head.revision_id) if head else None
        pending = session.scalar(select(func.count()).select_from(ShotRevision).where(ShotRevision.shot_id == self.id, ShotRevision.status == 'pending_review')) if head else 0
        return {'version': current.version_number if current else 1, 'status': current.status if current else ('approved' if self.status.value == 'approved' else 'baseline'), 'pending': pending, 'protected': bool(head)}

    @property
    def generation_details(self):
        import json
        from sqlalchemy.orm import object_session
        session = object_session(self)
        detail = session.get(ShotGenerationDetail, self.id) if session else None
        return json.loads(detail.content) if detail else None


class ShotGenerationDetail(Base):
    __tablename__ = "shot_generation_details"
    shot_id: Mapped[str] = mapped_column(String(32), ForeignKey("shots.id", ondelete="CASCADE"), primary_key=True)
    brief_id: Mapped[str] = mapped_column(String(40), ForeignKey("project_briefs.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class ShotRevision(Base):
    __tablename__ = "shot_revisions"
    __table_args__ = (UniqueConstraint('shot_id', 'version_number'),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: "rev_" + uuid.uuid4().hex)
    shot_id: Mapped[str] = mapped_column(String(32), ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("shot_revisions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default="{}")
    change_note: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")


class ShotRevisionHead(Base):
    __tablename__ = "shot_revision_heads"
    shot_id: Mapped[str] = mapped_column(String(32), ForeignKey("shots.id", ondelete="CASCADE"), primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(40), ForeignKey("shot_revisions.id"))


class ShotImage(Base):
    __tablename__ = "shot_images"
    revision_id: Mapped[str] = mapped_column(String(40), ForeignKey("shot_revisions.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(40), default=lambda: 'img_' + uuid.uuid4().hex)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    prompt: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default='{}')
    storage_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
