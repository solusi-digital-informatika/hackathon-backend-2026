from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.projects.model import Project, ProjectStatus
from app.modules.projects.schemas import ProjectCreate


class ProjectRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, data: ProjectCreate) -> Project:
        project = Project(
            name=data.name,
            description=data.description,
            status=ProjectStatus.draft,
        )
        self._db.add(project)
        self._db.commit()
        self._db.refresh(project)
        return project

    def list(self, limit: int, offset: int) -> tuple[list[Project], int]:
        total = self._db.scalar(select(func.count()).select_from(Project))
        rows = (
            self._db.execute(
                select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return list(rows), total or 0

    def get(self, project_id: str) -> Project | None:
        return self._db.get(Project, project_id)
