import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.brief.model import ProjectBrief, ReviewStatus, SourceDocument
from app.modules.brief.schemas import BriefUpdate, IngestRequest


class BriefRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # SourceDocument
    # ------------------------------------------------------------------

    def ingest(self, project_id: str, data: IngestRequest) -> SourceDocument:
        doc = SourceDocument(
            project_id=project_id,
            source_name=data.source_name,
            content=data.content,
        )
        self._db.add(doc)
        self._db.commit()
        self._db.refresh(doc)
        return doc

    def get_latest_doc(self, project_id: str) -> SourceDocument | None:
        return (
            self._db.execute(
                select(SourceDocument)
                .where(SourceDocument.project_id == project_id)
                .order_by(SourceDocument.created_at.desc())
            )
            .scalars()
            .first()
        )

    # ------------------------------------------------------------------
    # ProjectBrief
    # ------------------------------------------------------------------

    def get_brief(self, project_id: str) -> ProjectBrief | None:
        return (
            self._db.execute(
                select(ProjectBrief)
                .where(ProjectBrief.project_id == project_id)
                .order_by(ProjectBrief.created_at.desc())
            )
            .scalars()
            .first()
        )

    def create_brief(
        self, project_id: str, source_document_id: str, extracted: dict
    ) -> ProjectBrief:
        brief = ProjectBrief(
            project_id=project_id,
            source_document_id=source_document_id,
            objective=extracted.get("objective", ""),
            visual_style=extracted.get("visual_style", ""),
            lighting_mood=extracted.get("lighting_mood", ""),
            characters=json.dumps(extracted.get("characters", [])),
            key_props=json.dumps(extracted.get("key_props", [])),
            constraints=json.dumps(extracted.get("constraints", [])),
            unresolved_questions=json.dumps(extracted.get("unresolved_questions", [])),
            review_status=ReviewStatus.pending_review,
        )
        self._db.add(brief)
        self._db.commit()
        self._db.refresh(brief)
        return brief

    def update_brief(self, brief: ProjectBrief, data: BriefUpdate) -> ProjectBrief:
        if data.objective is not None:
            brief.objective = data.objective
        if data.visual_style is not None:
            brief.visual_style = data.visual_style
        if data.lighting_mood is not None:
            brief.lighting_mood = data.lighting_mood
        if data.characters is not None:
            brief.characters = json.dumps(
                [c.model_dump() for c in data.characters]
            )
        if data.key_props is not None:
            brief.key_props = json.dumps(
                [p.model_dump() for p in data.key_props]
            )
        if data.constraints is not None:
            brief.constraints = json.dumps(data.constraints)
        if data.unresolved_questions is not None:
            brief.unresolved_questions = json.dumps(data.unresolved_questions)
        if data.review_status is not None:
            brief.review_status = ReviewStatus(data.review_status)
        self._db.commit()
        self._db.refresh(brief)
        return brief
