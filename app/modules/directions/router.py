from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.database import get_db
from app.core.errors import error_body
from app.modules.directions import engine as impact_engine
from app.modules.directions.repository import DirectionRepository
from app.modules.directions.schemas import (
    AnalyzeOut,
    AnalyzeRequest,
    CompareOut,
    CompareRequest,
    DirectionCreate,
    DirectionList,
    DirectionOut,
    FieldDelta,
    ReviewRequest,
    ShotVersionOut,
    StoryboardOut,
    StoryboardShotEntry,
)
from app.modules.projects.repository import ProjectRepository
from app.modules.shots.repository import ShotRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["directions"])


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _require_project(project_id: str, db: Session) -> JSONResponse | None:
    if ProjectRepository(db).get(project_id) is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Project not found"),
        )
    return None


def _validation_fields(exc: ValidationError) -> list[dict]:
    fields = []
    for e in exc.errors():
        loc = e.get("loc", ())
        field_name = str(loc[-1]) if loc else "unknown"
        fields.append({"field": field_name, "message": e["msg"].capitalize()})
    return fields


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions
# ---------------------------------------------------------------------------


@router.post("/directions", status_code=201)
async def create_direction(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Direction input is invalid", []),
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Direction input is invalid", []),
        )

    try:
        data = DirectionCreate.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Direction input is invalid", _validation_fields(exc)),
        )

    direction = DirectionRepository(db).create(project_id, data)
    out = DirectionOut.model_validate(direction)
    return JSONResponse(
        status_code=201,
        content=out.model_dump(mode="json"),
        headers={"Location": f"/projects/{project_id}/directions/{direction.id}"},
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/directions
# ---------------------------------------------------------------------------


@router.get("/directions", response_model=DirectionList)
def list_directions(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    directions = DirectionRepository(db).list(project_id)
    return DirectionList(
        items=[DirectionOut.model_validate(d) for d in directions],
        total=len(directions),
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/directions/{direction_id}
# ---------------------------------------------------------------------------


@router.get("/directions/{direction_id}", response_model=DirectionOut)
def get_direction(project_id: str, direction_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    direction = DirectionRepository(db).get(project_id, direction_id)
    if direction is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Direction version not found"),
        )
    return DirectionOut.model_validate(direction)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions/compare
# ---------------------------------------------------------------------------


@router.post("/directions/compare", response_model=CompareOut)
async def compare_directions(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    try:
        raw = await request.json()
        data = CompareRequest.model_validate(raw)
    except (ValidationError, Exception) as exc:
        if isinstance(exc, ValidationError):
            return JSONResponse(
                status_code=400,
                content=error_body("validation_error", "Compare input is invalid", _validation_fields(exc)),
            )
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Compare input is invalid", []),
        )

    repo = DirectionRepository(db)
    base = repo.get(project_id, data.base_direction_id)
    target = repo.get(project_id, data.target_direction_id)

    if base is None or target is None:
        missing = "base" if base is None else "target"
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"Direction not found: {missing}"),
        )

    style_delta = None
    if base.visual_style != target.visual_style:
        style_delta = FieldDelta(base=base.visual_style, target=target.visual_style)

    lighting_delta = None
    if base.lighting_mood != target.lighting_mood:
        lighting_delta = FieldDelta(base=base.lighting_mood, target=target.lighting_mood)

    # Build a human-readable summary of what changed
    parts = []
    if style_delta:
        parts.append(f"Style shifted from '{base.visual_style}' to '{target.visual_style}'")
    if lighting_delta:
        parts.append(f"Lighting shifted from '{base.lighting_mood}' to '{target.lighting_mood}'")
    summary = "; ".join(parts) + "." if parts else "No differences detected between the two directions."

    return CompareOut(style_delta=style_delta, lighting_delta=lighting_delta, summary=summary)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions/analyze-impact
# ---------------------------------------------------------------------------


@router.post("/directions/analyze-impact", response_model=AnalyzeOut)
async def analyze_impact(project_id: str, request: Request, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    try:
        raw = await request.json()
        data = AnalyzeRequest.model_validate(raw)
    except (ValidationError, Exception) as exc:
        if isinstance(exc, ValidationError):
            return JSONResponse(
                status_code=400,
                content=error_body("validation_error", "Analyze input is invalid", _validation_fields(exc)),
            )
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Analyze input is invalid", []),
        )

    dir_repo = DirectionRepository(db)
    target = dir_repo.get(project_id, data.target_direction_id)
    if target is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Target direction not found"),
        )

    # Retrieve the baseline (lowest version_number in this project)
    all_directions = dir_repo.list(project_id)
    baseline = next((d for d in all_directions if d.id != target.id), None)

    base_style = baseline.visual_style if baseline else ""
    base_light = baseline.lighting_mood if baseline else ""

    # Retrieve all shots for this project, ordered by sequence_order
    shots, _ = ShotRepository(db).list(project_id)

    results = []
    for shot in shots:
        active_sv = dir_repo.get_active_shot_version(shot.id)

        # Collect text blobs to feed the engine
        shot_texts = [shot.title or "", shot.description or ""]
        if active_sv:
            shot_texts += [active_sv.prompt or "", active_sv.impact_reason or ""]

        result = impact_engine.analyze(
            base_visual_style=base_style,
            base_lighting_mood=base_light,
            target_visual_style=target.visual_style,
            target_lighting_mood=target.lighting_mood,
            shot_texts=shot_texts,
        )

        results.append(
            {
                "shot_id": shot.id,
                "action": result.action,
                "reason": result.reason,
                "confidence": result.confidence,
                "affected_requirements": result.affected_requirements,
            }
        )

    return AnalyzeOut(results=results)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/shots/{shot_id}/review
# ---------------------------------------------------------------------------


@router.post("/shots/{shot_id}/review", response_model=ShotVersionOut)
async def review_shot(
    project_id: str, shot_id: str, request: Request, db: Session = Depends(get_db)
):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    shot = ShotRepository(db).get(project_id, shot_id)
    if shot is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Shot not found"),
        )

    try:
        raw = await request.json()
        data = ReviewRequest.model_validate(raw)
    except (ValidationError, Exception) as exc:
        if isinstance(exc, ValidationError):
            return JSONResponse(
                status_code=400,
                content=error_body("validation_error", "Review input is invalid", _validation_fields(exc)),
            )
        return JSONResponse(
            status_code=400,
            content=error_body("validation_error", "Review input is invalid", []),
        )

    dir_repo = DirectionRepository(db)

    # Validate direction version exists and belongs to project
    direction = dir_repo.get(project_id, data.direction_version_id)
    if direction is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Direction version not found"),
        )

    # Find the ShotVersion tied to this direction, or create one
    sv = dir_repo.get_active_shot_version(shot.id)
    if sv is None or sv.direction_version_id != data.direction_version_id:
        # Create a new ShotVersion for this direction
        sv = dir_repo.create_shot_version(
            shot_id=shot.id,
            direction_version_id=data.direction_version_id,
            prompt="",
            action_recommendation=None,
            impact_reason="",
            confidence_score=None,
        )

    sv = dir_repo.record_review(sv, data)
    return ShotVersionOut.model_validate(sv)


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/storyboard
# ---------------------------------------------------------------------------


@router.get("/storyboard", response_model=StoryboardOut)
def get_storyboard(project_id: str, db: Session = Depends(get_db)):
    not_found = _require_project(project_id, db)
    if not_found:
        return not_found

    shots, _ = ShotRepository(db).list(project_id)
    dir_repo = DirectionRepository(db)

    entries = []
    for shot in shots:
        sv = dir_repo.get_active_shot_version(shot.id)
        asset = dir_repo.get_selected_asset(shot.id, sv.id if sv else None) if sv else None

        entries.append(
            StoryboardShotEntry(
                shot_id=shot.id,
                sequence_order=shot.sequence_order,
                title=shot.title,
                shot_status=shot.status.value,
                current_version_id=sv.id if sv else None,
                current_version_number=sv.version_number if sv else None,
                approved_action=sv.approved_action.value if sv and sv.approved_action else None,
                human_approval_status=(
                    sv.human_approval_status.value if sv else None
                ),
                asset_uri=asset.file_uri if asset else None,
                asset_type=asset.asset_type if asset else None,
            )
        )

    return StoryboardOut(project_id=project_id, shots=entries, total=len(entries))
