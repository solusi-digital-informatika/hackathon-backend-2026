from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.directions.model import (
    ActionRecommendation,
    Asset,
    DirectionVersion,
    HumanApprovalStatus,
    ShotVersion,
)
from app.modules.directions.schemas import DirectionCreate, ReviewRequest
from app.modules.shots.model import Shot


class DirectionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, project_id: str, data: DirectionCreate) -> DirectionVersion:
        direction = DirectionVersion(
            project_id=project_id,
            version_number=data.version_number,
            title=data.title,
            visual_style=data.visual_style,
            lighting_mood=data.lighting_mood,
            change_note=data.change_note,
            status=data.status,
        )
        self._db.add(direction)
        self._db.commit()
        self._db.refresh(direction)
        return direction

    def list(self, project_id: str) -> list[DirectionVersion]:
        rows = (
            self._db.execute(
                select(DirectionVersion)
                .where(DirectionVersion.project_id == project_id)
                .order_by(DirectionVersion.version_number.asc())
            )
            .scalars()
            .all()
        )
        return list(rows)

    def get(self, project_id: str, direction_id: str) -> DirectionVersion | None:
        return (
            self._db.execute(
                select(DirectionVersion).where(
                    DirectionVersion.id == direction_id,
                    DirectionVersion.project_id == project_id,
                )
            )
            .scalars()
            .first()
        )

    def get_by_id(self, direction_id: str) -> DirectionVersion | None:
        return self._db.get(DirectionVersion, direction_id)

    # ------------------------------------------------------------------
    # Shot Version helpers
    # ------------------------------------------------------------------

    def get_active_shot_version(self, shot_id: str) -> ShotVersion | None:
        """Return the highest-version ShotVersion for a shot (latest)."""
        return (
            self._db.execute(
                select(ShotVersion)
                .where(ShotVersion.shot_id == shot_id)
                .order_by(ShotVersion.version_number.desc())
            )
            .scalars()
            .first()
        )

    def get_shot_versions(self, shot_id: str) -> list[ShotVersion]:
        rows = (
            self._db.execute(
                select(ShotVersion)
                .where(ShotVersion.shot_id == shot_id)
                .order_by(ShotVersion.version_number.asc())
            )
            .scalars()
            .all()
        )
        return list(rows)

    def create_shot_version(
        self,
        shot_id: str,
        direction_version_id: str,
        prompt: str,
        action_recommendation: ActionRecommendation | None,
        impact_reason: str,
        confidence_score: float | None,
    ) -> ShotVersion:
        max_ver = self._db.scalar(
            select(func.max(ShotVersion.version_number)).where(ShotVersion.shot_id == shot_id)
        )
        next_ver = (max_ver or 0) + 1

        sv = ShotVersion(
            shot_id=shot_id,
            version_number=next_ver,
            direction_version_id=direction_version_id,
            prompt=prompt,
            action_recommendation=action_recommendation,
            human_approval_status=HumanApprovalStatus.pending,
            impact_reason=impact_reason,
            confidence_score=confidence_score,
        )
        self._db.add(sv)
        self._db.commit()
        self._db.refresh(sv)
        return sv

    def record_review(
        self,
        shot_version: ShotVersion,
        data: ReviewRequest,
    ) -> ShotVersion:
        shot_version.human_approval_status = HumanApprovalStatus.approved
        shot_version.approved_action = data.approved_action
        shot_version.note = data.note
        if data.prompt:
            shot_version.prompt = data.prompt
        if data.impact_reason:
            shot_version.impact_reason = data.impact_reason
        self._db.commit()
        self._db.refresh(shot_version)
        return shot_version

    # ------------------------------------------------------------------
    # Asset helpers
    # ------------------------------------------------------------------

    def get_selected_asset(self, shot_id: str, shot_version_id: str | None) -> Asset | None:
        q = select(Asset).where(Asset.shot_id == shot_id)
        if shot_version_id:
            q = q.where(Asset.shot_version_id == shot_version_id)
        q = q.order_by(Asset.created_at.desc())
        return self._db.execute(q).scalars().first()

    def create_asset(
        self,
        shot_id: str,
        shot_version_id: str | None,
        asset_type: str,
        file_uri: str,
    ) -> Asset:
        asset = Asset(
            shot_id=shot_id,
            shot_version_id=shot_version_id,
            asset_type=asset_type,
            file_uri=file_uri,
        )
        self._db.add(asset)
        self._db.commit()
        self._db.refresh(asset)
        return asset
