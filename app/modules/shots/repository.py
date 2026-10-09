from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.shots.model import Shot, ShotStatus
from app.modules.shots.schemas import ShotCreate, ShotUpdate


class ShotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _next_sequence_order(self, project_id: str) -> int:
        max_order = self._db.scalar(
            select(func.max(Shot.sequence_order)).where(Shot.project_id == project_id)
        )
        return (max_order or 0) + 1

    def create(self, project_id: str, data: ShotCreate) -> Shot:
        order = data.sequence_order or self._next_sequence_order(project_id)
        shot = Shot(
            project_id=project_id,
            sequence_order=order,
            title=data.title,
            description=data.description,
            status=ShotStatus.draft,
        )
        self._db.add(shot)
        self._db.commit()
        self._db.refresh(shot)
        return shot

    def list(self, project_id: str) -> tuple[list[Shot], int]:
        rows = (
            self._db.execute(
                select(Shot)
                .where(Shot.project_id == project_id)
                .order_by(Shot.sequence_order.asc())
            )
            .scalars()
            .all()
        )
        shots = list(rows)
        return shots, len(shots)

    def get(self, project_id: str, shot_id: str) -> Shot | None:
        return (
            self._db.execute(
                select(Shot).where(Shot.id == shot_id, Shot.project_id == project_id)
            )
            .scalars()
            .first()
        )

    def update(self, shot: Shot, data: ShotUpdate) -> Shot:
        if data.title is not None:
            shot.title = data.title
        if data.description is not None:
            shot.description = data.description
        if data.status is not None:
            shot.status = data.status
        if data.sequence_order is not None:
            shot.sequence_order = data.sequence_order
        self._db.commit()
        self._db.refresh(shot)
        return shot

    def delete(self, shot: Shot) -> None:
        self._db.delete(shot)
        self._db.commit()
