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
import json
from sqlalchemy import func, select
from app.core.ai_provider import ProviderError
from app.modules.brief.creative import GenerateRequest, generate
from app.modules.brief.model import CreativePlan, ProjectBrief, SourceDocument
from app.modules.projects.model import Project
from app.modules.shots.model import Shot, ShotGenerationDetail
from app.modules.brief.storyboard import StoryboardRequest, generate_storyboard


def brief_output(row, db):
    out = ProjectBriefOut.from_orm_row(row)
    plan = db.get(CreativePlan, row.id)
    if plan:
        out.version = plan.version
        out.creative_sections = json.loads(plan.sections)
        out.storyboard = json.loads(plan.storyboard)
        out.generated_shot_ids = json.loads(plan.shot_ids)
    else:
        ids = list(db.scalars(select(ProjectBrief.id).where(ProjectBrief.project_id == row.project_id).order_by(ProjectBrief.created_at, ProjectBrief.id)))
        out.version = ids.index(row.id) + 1
    return out

router = APIRouter(prefix="/projects/{project_id}/brief", tags=["brief"])


@router.post("/storyboard", status_code=200)
def create_storyboard(project_id: str, data: StoryboardRequest, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found
    brief = BriefRepository(db).get_brief(project_id)
    if not brief or brief.id != data.brief_id:
        return JSONResponse(status_code=409, content=error_body("brief_changed", "Open the current brief before generating shots."))
    plan = db.get(CreativePlan, brief.id)
    if not plan:
        return JSONResponse(status_code=400, content=error_body("brief_required", "Create an AI creative brief first."))
    if json.loads(plan.shot_ids):
        return brief_output(brief, db).model_dump(mode="json")
    snapshot = brief.updated_at
    try:
        result = generate_storyboard(ProjectBriefOut.from_orm_row(brief).model_dump(mode="json"), json.loads(plan.sections), data.shot_count)
    except ProviderError as exc:
        return JSONResponse(status_code=502 if exc.code == "ai_invalid_output" else 503, content=error_body(exc.code, "Shot details could not be generated. Please try again."))
    db.execute(select(Project).where(Project.id == project_id).with_for_update())
    db.refresh(brief)
    db.refresh(plan)
    latest = BriefRepository(db).get_brief(project_id)
    if latest.id != brief.id or brief.updated_at != snapshot:
        return JSONResponse(status_code=409, content=error_body("brief_changed", "The brief changed during generation. Please try again."))
    if json.loads(plan.shot_ids):
        return brief_output(brief, db).model_dump(mode="json")
    order = db.scalar(select(func.max(Shot.sequence_order)).where(Shot.project_id == project_id)) or 0
    shots = [Shot(project_id=project_id, sequence_order=order + i + 1, title=shot.title, description=shot.description) for i, shot in enumerate(result.shots)]
    db.add_all(shots)
    db.flush()
    db.add_all([ShotGenerationDetail(shot_id=shot.id, brief_id=brief.id, content=detail.model_dump_json()) for shot, detail in zip(shots, result.shots)])
    plan.storyboard = json.dumps([shot.model_dump() for shot in result.shots], ensure_ascii=False)
    plan.shot_ids = json.dumps([shot.id for shot in shots])
    db.commit()
    return brief_output(brief, db).model_dump(mode="json")


@router.post("/generate", status_code=201)
def generate_brief(project_id: str, data: GenerateRequest, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found
    try:
        result = generate(data)
    except ProviderError as exc:
        message = "AI belum dikonfigurasi di server." if exc.code == "ai_not_configured" else "AI belum dapat menghasilkan brief yang valid. Silakan coba lagi."
        return JSONResponse(status_code=503 if exc.code != "ai_invalid_output" else 502, content=error_body(exc.code, message))
    if result.relevance == "irrelevant":
        return JSONResponse(status_code=422, content=error_body("irrelevant_brief", result.reason))
    # Serialize concurrent generation within a project, then save the whole plan atomically.
    db.execute(select(Project).where(Project.id == project_id).with_for_update())
    version = (db.scalar(select(func.count()).select_from(ProjectBrief).where(ProjectBrief.project_id == project_id)) or 0) + 1
    doc = SourceDocument(project_id=project_id, source_name=data.source_name, content=data.content)
    db.add(doc)
    db.flush()
    fields = result.model_dump(exclude={"relevance", "reason", "sections", "storyboard"})
    for key in ("characters", "key_props", "constraints", "unresolved_questions"):
        fields[key] = json.dumps(fields[key], ensure_ascii=False)
    brief = ProjectBrief(project_id=project_id, source_document_id=doc.id, **fields)
    db.add(brief)
    db.flush()
    db.add(CreativePlan(brief_id=brief.id, version=version, sections=result.sections.model_dump_json(),
                        storyboard="[]", shot_ids="[]"))
    db.commit()
    return BriefOut(source_document=SourceDocumentOut.model_validate(doc), brief=brief_output(brief, db)).model_dump(mode="json")


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
    return brief_output(brief, db).model_dump(mode="json")


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/brief
# ---------------------------------------------------------------------------


@router.get("", status_code=200)
def get_brief(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    repo = BriefRepository(db)
    brief = repo.get_brief(project_id)
    doc = db.get(SourceDocument, brief.source_document_id) if brief and brief.source_document_id else None

    if doc is None or brief is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "No brief found for this project"),
        )

    out = BriefOut(
        source_document=SourceDocumentOut.model_validate(doc),
        brief=brief_output(brief, db),
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

    if data.creative_sections is not None:
        plan = db.get(CreativePlan, brief.id)
        if plan is None:
            return JSONResponse(status_code=400, content=error_body("validation_error", "This brief has no creative plan. Create an AI brief first."))
        plan.sections = json.dumps(data.creative_sections, ensure_ascii=False)
    updated = repo.update_brief(brief, data)
    return brief_output(updated, db).model_dump(mode="json")
