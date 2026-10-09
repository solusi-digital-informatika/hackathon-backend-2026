from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.database import get_db
from app.core.errors import error_body
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectList, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


def _validation_fields(exc: ValidationError) -> list[dict]:
    fields = []
    for e in exc.errors():
        loc = e.get("loc", ())
        field_name = str(loc[-1]) if loc else "unknown"
        fields.append({"field": field_name, "message": e["msg"].capitalize()})
    return fields


@router.post("", status_code=201)
async def create_project(request: Request, db: Session = Depends(get_db)):
    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Project input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Project input is invalid", []),
        )

    # status is not accepted on create
    if "status" in raw:
        return JSONResponse(
            status_code=400,
            content=error_body(
                "validation_error",
                "Project input is invalid",
                [{"field": "status", "message": "Not accepted on create"}],
            ),
        )

    try:
        data = ProjectCreate.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body(
                "validation_error", "Project input is invalid", _validation_fields(exc)
            ),
        )

    repo = ProjectRepository(db)
    project = repo.create(data)
    out = ProjectOut.model_validate(project)
    return JSONResponse(
        status_code=201,
        content=out.model_dump(mode="json"),
        headers={"Location": f"/projects/{project.id}"},
    )


@router.get("", response_model=ProjectList)
def list_projects(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100:
        return JSONResponse(
            status_code=400,
            content=error_body(
                "validation_error",
                "Project input is invalid",
                [{"field": "limit", "message": "Must be between 1 and 100"}],
            ),
        )
    if offset < 0:
        return JSONResponse(
            status_code=400,
            content=error_body(
                "validation_error",
                "Project input is invalid",
                [{"field": "offset", "message": "Must be >= 0"}],
            ),
        )

    repo = ProjectRepository(db)
    items, total = repo.list(limit=limit, offset=offset)
    return ProjectList(
        items=[ProjectOut.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.get(project_id)
    if project is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Project not found"),
        )
    return ProjectOut.model_validate(project)
