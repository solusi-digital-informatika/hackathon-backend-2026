from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.database import get_db
from app.core.errors import error_body
from app.modules.brief import extractor
from app.modules.brief.repository import BriefRepository
from app.modules.brief.schemas import (
    BriefOut,
    BriefUpdate,
    IngestRequest,
    ProjectBriefOut,
    SourceDocumentOut,
)
from app.modules.projects.repository import ProjectRepository

router = APIRouter(prefix="/projects/{project_id}/brief", tags=["brief"])


def _validation_fields(exc: ValidationError) -> list[dict]:
    fields = []
    for e in exc.errors():
        loc = e.get("loc", ())
        field_name = str(loc[-1]) if loc else "unknown"
        fields.append({"field": field_name, "message": e["msg"].capitalize()})
    return fields


def _require_project(project_id: str, db: Session) -> JSONResponse | None:
    if ProjectRepository(db).get(project_id) is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Project not found"),
        )
    return None


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/brief/ingest
# ---------------------------------------------------------------------------


@router.post("/ingest", status_code=201)
async def ingest_brief(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", []),
        )

    try:
        data = IngestRequest.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", _validation_fields(exc)),
        )

    doc = BriefRepository(db).ingest(project_id, data)
    out = SourceDocumentOut.model_validate(doc)
    return JSONResponse(
        status_code=201,
        content=out.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/brief/extract
# ---------------------------------------------------------------------------


@router.post("/extract", status_code=200)
def extract_brief(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = BriefRepository(db)
    doc = repo.get_latest_doc(project_id)
    if doc is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "No source document found for this project"),
        )

    extracted = extractor.extract(doc.content)
    brief = repo.create_brief(project_id, doc.id, extracted)
    return ProjectBriefOut.from_orm_row(brief).model_dump(mode="json")


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/brief
# ---------------------------------------------------------------------------


@router.get("", status_code=200)
def get_brief(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = BriefRepository(db)
    doc = repo.get_latest_doc(project_id)
    brief = repo.get_brief(project_id)

    if doc is None or brief is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "No brief found for this project"),
        )

    out = BriefOut(
        source_document=SourceDocumentOut.model_validate(doc),
        brief=ProjectBriefOut.from_orm_row(brief),
    )
    return out.model_dump(mode="json")


# ---------------------------------------------------------------------------
# PUT /projects/{project_id}/brief
# ---------------------------------------------------------------------------


@router.put("", status_code=200)
async def update_brief(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = BriefRepository(db)
    brief = repo.get_brief(project_id)
    if brief is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "No brief found for this project"),
        )

    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", []),
        )

    try:
        data = BriefUpdate.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Brief input is invalid", _validation_fields(exc)),
        )

    updated = repo.update_brief(brief, data)
    return ProjectBriefOut.from_orm_row(updated).model_dump(mode="json")
