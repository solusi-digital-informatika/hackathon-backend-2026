import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_doc_id() -> str:
    return "doc_" + uuid.uuid4().hex[:8]


def _new_brief_id() -> str:
    return "brief_" + uuid.uuid4().hex[:8]


class ReviewStatus(str, enum.Enum):
    pending_review = "pending_review"
    approved = "approved"


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_doc_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class ProjectBrief(Base):
    __tablename__ = "project_briefs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_new_brief_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_document_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visual_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lighting_mood: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON arrays stored as Text; serialization handled in the repository layer
    characters: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    key_props: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    constraints: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    unresolved_questions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"),
        nullable=False,
        default=ReviewStatus.pending_review,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class CreativePlan(Base):
    __tablename__ = "creative_brief_plans"
    brief_id: Mapped[str] = mapped_column(String(40), ForeignKey("project_briefs.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sections: Mapped[str] = mapped_column(Text, nullable=False)
    storyboard: Mapped[str] = mapped_column(Text, nullable=False)
    shot_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
