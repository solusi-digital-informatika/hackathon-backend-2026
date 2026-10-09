import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_dir_id() -> str:
    return "dir_" + uuid.uuid4().hex[:8]


def _new_sver_id() -> str:
    return "sver_" + uuid.uuid4().hex[:8]


def _new_ast_id() -> str:
    return "ast_" + uuid.uuid4().hex[:8]


class DirectionStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ActionRecommendation(str, enum.Enum):
    retain = "retain"
    adapt = "adapt"
    regenerate = "regenerate"
    needs_review = "needs_review"


class HumanApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    overridden = "overridden"


class AssetSelectionStatus(str, enum.Enum):
    selected = "selected"
    alternative = "alternative"


class DirectionVersion(Base):
    __tablename__ = "direction_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_new_dir_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    visual_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lighting_mood: Mapped[str] = mapped_column(Text, nullable=False, default="")
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[DirectionStatus] = mapped_column(
        Enum(DirectionStatus, name="direction_status"), nullable=False, default=DirectionStatus.draft
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class ShotVersion(Base):
    __tablename__ = "shot_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_new_sver_id)
    shot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    direction_version_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("direction_versions.id", ondelete="CASCADE"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_recommendation: Mapped[ActionRecommendation | None] = mapped_column(
        Enum(ActionRecommendation, name="action_recommendation"), nullable=True
    )
    human_approval_status: Mapped[HumanApprovalStatus] = mapped_column(
        Enum(HumanApprovalStatus, name="human_approval_status"),
        nullable=False,
        default=HumanApprovalStatus.pending,
    )
    # Human override: what the director decided (may differ from action_recommendation)
    approved_action: Mapped[ActionRecommendation | None] = mapped_column(
        Enum(ActionRecommendation, name="approved_action"), nullable=True
    )
    impact_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_new_ast_id)
    shot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shot_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("shot_versions.id", ondelete="SET NULL"), nullable=True
    )
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False, default="image/png")
    file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    selection_status: Mapped[AssetSelectionStatus] = mapped_column(
        Enum(AssetSelectionStatus, name="asset_selection_status"),
        nullable=False,
        default=AssetSelectionStatus.selected,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
