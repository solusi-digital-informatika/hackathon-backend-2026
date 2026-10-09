from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.database import get_db
from app.core.errors import error_body
from app.modules.projects.repository import ProjectRepository
from app.modules.shots.repository import ShotRepository
from app.modules.shots.schemas import ShotCreate, ShotList, ShotOut, ShotUpdate
from app.modules.shots.model import ShotRevisionHead

router = APIRouter(prefix="/projects/{project_id}/shots", tags=["shots"])


def _validation_fields(exc: ValidationError) -> list[dict]:
    fields = []
    for e in exc.errors():
        loc = e.get("loc", ())
        field_name = str(loc[-1]) if loc else "unknown"
        fields.append({"field": field_name, "message": e["msg"].capitalize()})
    return fields


def _require_project(project_id: str, db: Session) -> JSONResponse | None:
    """Return a 404 JSONResponse if the project does not exist, else None."""
    repo = ProjectRepository(db)
    if repo.get(project_id) is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Project not found"),
        )
    return None


@router.post("", status_code=201)
async def create_shot(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", []),
        )

    try:
        data = ShotCreate.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", _validation_fields(exc)),
        )

    shot = ShotRepository(db).create(project_id, data)
    out = ShotOut.model_validate(shot)
    return JSONResponse(
        status_code=201,
        content=out.model_dump(mode="json"),
        headers={"Location": f"/projects/{project_id}/shots/{shot.id}"},
    )


@router.get("", response_model=ShotList)
def list_shots(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    shots, total = ShotRepository(db).list(project_id)
    return ShotList(
        items=[ShotOut.model_validate(s) for s in shots],
        total=total,
    )


@router.get("/{shot_id}", response_model=ShotOut)
def get_shot(project_id: str, shot_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    shot = ShotRepository(db).get(project_id, shot_id)
    if shot is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Shot not found"),
        )
    return ShotOut.model_validate(shot)


@router.patch("/{shot_id}", response_model=ShotOut)
async def update_shot(
    project_id: str, shot_id: str, request: Request, db: Session = Depends(get_db)
):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = ShotRepository(db)
    shot = repo.get(project_id, shot_id)
    if shot is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Shot not found"),
        )

    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", []),
        )

    try:
        data = ShotUpdate.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Shot input is invalid", _validation_fields(exc)),
        )

    db.refresh(shot, with_for_update=True)
    if db.get(ShotRevisionHead, shot.id) and any(getattr(data, field) is not None for field in ('title', 'description', 'status')):
        return JSONResponse(status_code=409, content=error_body('revision_required', 'Create and review a revision to change this versioned shot.'))
    shot = repo.update(shot, data)
    return ShotOut.model_validate(shot)


@router.delete("/{shot_id}", status_code=204)
def delete_shot(project_id: str, shot_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = ShotRepository(db)
    shot = repo.get(project_id, shot_id)
    if shot is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Shot not found"),
        )

    if db.get(ShotRevisionHead, shot.id):
        return JSONResponse(status_code=409, content=error_body('revision_history_protected', 'This shot has version history and cannot be deleted.'))
    repo.delete(shot)
    return Response(status_code=204)
