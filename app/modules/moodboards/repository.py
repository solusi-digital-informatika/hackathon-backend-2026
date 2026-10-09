from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.moodboards.model import ExtractionVersion, Moodboard, MoodboardExport, MoodboardSource


class MoodboardRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, project_id, moodboard_id, lock=False):
        query = select(Moodboard).where(Moodboard.project_id == project_id, Moodboard.id == moodboard_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)

    def sources(self, moodboard_id, included_only=False):
        query = select(MoodboardSource).where(MoodboardSource.moodboard_id == moodboard_id)
        if included_only:
            query = query.where(MoodboardSource.included.is_(True))
        return list(self.db.scalars(query.order_by(MoodboardSource.sequence_order, MoodboardSource.id)))

    def version(self, moodboard_id, version_id, lock=False):
        query = select(ExtractionVersion).where(ExtractionVersion.moodboard_id == moodboard_id,
                                               ExtractionVersion.id == version_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)

    def export(self, moodboard_id, export_id):
        return self.db.scalar(select(MoodboardExport).join(ExtractionVersion).where(
            ExtractionVersion.moodboard_id == moodboard_id, MoodboardExport.id == export_id))
