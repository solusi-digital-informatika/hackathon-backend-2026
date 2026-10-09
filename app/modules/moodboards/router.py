import copy
import json
import re
from datetime import datetime, timezone
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.modules.projects.model import Project
from app.modules.moodboards.model import ExtractionVersion, Moodboard, MoodboardExport, MoodboardSource, ReviewEvent
from app.modules.moodboards.provider import ProviderError, VisionProvider, validate_translation
from app.modules.moodboards.repository import MoodboardRepository
from app.modules.moodboards.schemas import (AnalysisRequest, ApprovalRequest, ExportRequest, HumanSummary,
    MoodboardCreate, MoodboardOut, MoodboardUpdate, ReviewRequest, SourceUpdate)
from app.modules.moodboards.service import (check_revision, content_hash, problem, render_markdown,
    reviewed_summary, text_value, validate_source_links)
from app.modules.moodboards.storage import InvalidImage, prepare_image, remove_image, save_image, storage_path

router = APIRouter(prefix="/projects/{project_id}/moodboards", tags=["moodboards"])


def require_project(db, project_id, write=False):
    project = db.get(Project, project_id)
    if project is None:
        problem(404, "not_found", "Project tidak ditemukan")
    if write and project.status == "archived":
        problem(409, "project_archived", "Project arsip hanya dapat dibaca")
    return project


def require_board(db, project_id, board_id, write=False, allow_archived=False):
    require_project(db, project_id, write)
    board = MoodboardRepository(db).get(project_id, board_id, lock=write)
    if board is None:
        problem(404, "not_found", "Moodboard tidak ditemukan")
    if write and board.archived and not allow_archived:
        problem(409, "moodboard_archived", "Pulihkan moodboard sebelum mengubah data")
    return board


def require_version(db, board_id, version_id, lock=False):
    version = MoodboardRepository(db).version(board_id, version_id, lock)
    if version is None:
        problem(404, "not_found", "Versi tidak ditemukan")
    return version


def public_source(source):
    return {key: getattr(source, key) for key in ("id", "original_filename", "checksum", "mime_type", "width",
            "height", "size_bytes", "label", "notes", "roles", "roles_confirmed", "included",
            "sequence_order", "warnings", "created_at")}


def public_version(version):
    snapshot = copy.deepcopy(version.snapshot)
    for source in snapshot["sources"]:
        source.pop("analysis_key", None)
    return {"id": version.id, "version_number": version.version_number, "revision": version.revision,
            "based_on_version_id": version.based_on_version_id, "review_status": version.review_status,
            "job_status": version.job_status, "stage": version.stage, "snapshot": snapshot,
            "per_source": version.per_source, "original_result": version.original_result,
            "human_summary": version.reviewed_result, "findings": version.findings,
            "conflict_resolutions": version.conflict_resolutions, "instructions": version.instructions,
            "error_code": version.error_code, "provider_metadata": version.provider_metadata,
            "created_at": version.created_at, "approved_at": version.approved_at}


def export_preview(export):
    return {"id": export.id, "language": export.language, "status": export.status, "filename": export.filename,
            "content": export.content, "content_hash": export.content_hash,
            "template_version": export.template_version, "created_at": export.created_at}


def idempotency_key(value):
    if not value or len(value) > 100 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        problem(400, "validation_error", "Idempotency-Key wajib, maksimal 100 karakter ASCII")
    return value


@router.post("", status_code=201)
def create_moodboard(project_id: str, data: MoodboardCreate, db: Session = Depends(get_db)):
    require_project(db, project_id, write=True)
    board = Moodboard(project_id=project_id, **data.model_dump())
    db.add(board)
    db.commit()
    db.refresh(board)
    return MoodboardOut.model_validate(board)


@router.get("")
def list_moodboards(project_id: str, archived: bool = False, limit: int = Query(20, ge=1, le=100),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    require_project(db, project_id)
    filters = (Moodboard.project_id == project_id, Moodboard.archived == archived)
    total = db.scalar(select(func.count()).select_from(Moodboard).where(*filters))
    boards = db.scalars(select(Moodboard).where(*filters).order_by(Moodboard.created_at.desc(), Moodboard.id)
                        .limit(limit).offset(offset))
    items = []
    for board in boards:
        item = MoodboardOut.model_validate(board).model_dump()
        item["source_count"] = db.scalar(select(func.count()).select_from(MoodboardSource).where(
            MoodboardSource.moodboard_id == board.id, MoodboardSource.included.is_(True)))
        latest = db.scalar(select(ExtractionVersion).where(ExtractionVersion.moodboard_id == board.id)
                           .order_by(ExtractionVersion.version_number.desc()).limit(1))
        item["latest_job_status"] = latest.job_status if latest else None
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{board_id}")
def get_moodboard(project_id: str, board_id: str, db: Session = Depends(get_db)):
    board = require_board(db, project_id, board_id)
    result = MoodboardOut.model_validate(board).model_dump()
    result["sources"] = [public_source(s) for s in MoodboardRepository(db).sources(board_id)]
    return result


@router.patch("/{board_id}")
def update_moodboard(project_id: str, board_id: str, data: MoodboardUpdate, db: Session = Depends(get_db)):
    board = require_board(db, project_id, board_id, write=True, allow_archived=True)
    check_revision(board, data.revision)
    if board.archived and data.archived is not False:
        problem(409, "moodboard_archived", "Pulihkan moodboard sebelum mengubah metadata")
    for key, value in data.model_dump(exclude={"revision"}, exclude_none=True).items():
        setattr(board, key, value)
    board.revision += 1
    db.commit()
    return MoodboardOut.model_validate(board)


@router.post("/{board_id}/sources", status_code=201)
async def upload_sources(project_id: str, board_id: str, files: list[UploadFile] = File(...),
                         revision: int = Form(..., ge=1), db: Session = Depends(get_db)):
    board = require_board(db, project_id, board_id, write=True)
    check_revision(board, revision)
    sources = MoodboardRepository(db).sources(board_id)
    included = [s for s in sources if s.included]
    count, total = len(included), sum(s.size_bytes for s in included)
    results, saved = [], []
    try:
        for upload in files:
            filename = PurePath((upload.filename or "image").replace("\\", "/")).name[:255]
            data = await upload.read(settings.moodboard_max_file_bytes + 1)
            await upload.close()
            try:
                metadata, preview = prepare_image(data)
            except InvalidImage as exc:
                results.append({"filename": filename, "status": "rejected", "message": str(exc)})
                continue
            duplicate = next((s for s in sources if s.checksum == metadata["checksum"]), None)
            if duplicate:
                results.append({"filename": filename, "status": "duplicate", "source": public_source(duplicate)})
                continue
            if count >= settings.moodboard_max_sources or total + len(data) > settings.moodboard_max_total_bytes:
                results.append({"filename": filename, "status": "rejected", "message": "Batas jumlah/total ukuran sumber tercapai"})
                continue
            keys = save_image(data, preview)
            saved.extend(keys)
            source = MoodboardSource(moodboard_id=board_id, original_filename=filename,
                                    storage_key=keys[0], analysis_key=keys[1], sequence_order=len(sources) + 1,
                                    **metadata)
            db.add(source)
            db.flush()
            sources.append(source)
            count += 1
            total += len(data)
            results.append({"filename": filename, "status": "created", "source": public_source(source)})
        if saved:
            board.revision += 1
        db.commit()
    except Exception:
        db.rollback()
        remove_image(*saved)
        raise
    return {"revision": board.revision, "items": results}


@router.patch("/{board_id}/sources/{source_id}")
def update_source(project_id: str, board_id: str, source_id: str, data: SourceUpdate, db: Session = Depends(get_db)):
    board = require_board(db, project_id, board_id, write=True)
    check_revision(board, data.revision)
    source = db.scalar(select(MoodboardSource).where(MoodboardSource.id == source_id, MoodboardSource.moodboard_id == board_id))
    if source is None:
        problem(404, "not_found", "Sumber tidak ditemukan")
    if data.included and not source.included:
        active = MoodboardRepository(db).sources(board_id, included_only=True)
        if len(active) >= settings.moodboard_max_sources or sum(s.size_bytes for s in active) + source.size_bytes > settings.moodboard_max_total_bytes:
            problem(400, "source_limit", "Batas sumber tercapai")
    for key, value in data.model_dump(exclude={"revision"}, exclude_none=True).items():
        setattr(source, key, value)
    if data.roles is not None:
        source.roles_confirmed = True
    board.revision += 1
    db.commit()
    return {"revision": board.revision, "source": public_source(source)}


@router.get("/{board_id}/sources/{source_id}/file")
def source_file(project_id: str, board_id: str, source_id: str, preview: bool = False, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    source = db.scalar(select(MoodboardSource).where(MoodboardSource.id == source_id, MoodboardSource.moodboard_id == board_id))
    if source is None:
        problem(404, "not_found", "Sumber tidak ditemukan")
    path = storage_path(source.analysis_key if preview else source.storage_key)
    if not path.is_file():
        problem(404, "source_missing", "File sumber tidak tersedia")
    return FileResponse(path, media_type="image/jpeg" if preview else source.mime_type,
                        filename=source.original_filename, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/{board_id}/analyses", status_code=202)
def analyze(project_id: str, board_id: str, data: AnalysisRequest, request: Request,
            key: str | None = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    key = idempotency_key(key)
    board = require_board(db, project_id, board_id, write=True)
    request_hash = content_hash(json.dumps(data.model_dump(), sort_keys=True))
    existing = db.scalar(select(ExtractionVersion).where(ExtractionVersion.moodboard_id == board_id,
                                                       ExtractionVersion.idempotency_key == key))
    if existing:
        if existing.request_hash != request_hash:
            problem(409, "idempotency_conflict", "Key telah dipakai dengan payload berbeda")
        return public_version(existing)
    check_revision(board, data.revision)
    if data.based_on_version_id:
        require_version(db, board_id, data.based_on_version_id)
    if not settings.ai_api_key or not settings.ai_vision_model:
        problem(503, "ai_not_configured", "Atur AI_API_KEY dan AI_VISION_MODEL sebelum analisis")
    active = db.scalar(select(ExtractionVersion.id).where(ExtractionVersion.moodboard_id == board_id,
                       ExtractionVersion.job_status.in_(["queued", "running"])))
    if active:
        problem(409, "analysis_running", "Analisis moodboard masih berjalan")
    sources = MoodboardRepository(db).sources(board_id, included_only=True)
    if not sources:
        problem(400, "no_sources", "Upload minimal satu gambar valid")
    number = (db.scalar(select(func.max(ExtractionVersion.version_number)).where(ExtractionVersion.moodboard_id == board_id)) or 0) + 1
    snapshot_sources = []
    for i, source in enumerate(sources, 1):
        snapshot_sources.append({"id": source.id, "prefix": f"G{i}", "original_filename": source.original_filename,
            "checksum": source.checksum, "analysis_key": source.analysis_key, "label": source.label,
            "notes": source.notes, "roles": source.roles, "roles_confirmed": source.roles_confirmed,
            "warnings": source.warnings})
    project = require_project(db, project_id)
    version = ExtractionVersion(moodboard_id=board_id, version_number=number,
        based_on_version_id=data.based_on_version_id, idempotency_key=key, request_hash=request_hash,
        snapshot={"title": board.title, "context": board.context, "intended_use": board.intended_use,
                  "project_name": project.name, "sources": snapshot_sources})
    db.add(version)
    db.commit()
    db.refresh(version)
    result = public_version(version)
    request.app.state.moodboard_runner.submit(version.id)
    return result


@router.get("/{board_id}/versions")
def list_versions(project_id: str, board_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    versions = db.scalars(select(ExtractionVersion).where(ExtractionVersion.moodboard_id == board_id)
                         .order_by(ExtractionVersion.version_number.desc()))
    return {"items": [public_version(v) for v in versions]}


@router.get("/{board_id}/versions/{version_id}")
@router.get("/{board_id}/analyses/{version_id}")
def get_version(project_id: str, board_id: str, version_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    return public_version(require_version(db, board_id, version_id))


@router.post("/{board_id}/analyses/{version_id}/cancel")
def cancel_analysis(project_id: str, board_id: str, version_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id, write=True)
    version = require_version(db, board_id, version_id, lock=True)
    if version.job_status not in {"queued", "running"}:
        problem(409, "invalid_state", "Job sudah selesai")
    version.job_status, version.stage = "cancelled", "cancelled"
    db.commit()
    return public_version(version)


@router.post("/{board_id}/analyses/{version_id}/retry", status_code=202)
def retry_analysis(project_id: str, board_id: str, version_id: str, request: Request, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id, write=True)
    version = require_version(db, board_id, version_id, lock=True)
    if version.job_status not in {"partial", "failed"}:
        problem(409, "invalid_state", "Hanya job gagal atau parsial yang dapat diulang")
    if db.scalar(select(ExtractionVersion.id).where(ExtractionVersion.moodboard_id == board_id,
            ExtractionVersion.job_status.in_(["queued", "running"]))):
        problem(409, "analysis_running", "Analisis moodboard masih berjalan")
    version.job_status, version.stage = "queued", "queued"
    version.revision += 1
    if version.original_result:
        db.add(ReviewEvent(version_id=version.id, event_type="partial_retry", payload={
            "original_result": version.original_result, "reviewed_result": version.reviewed_result,
            "findings": version.findings, "conflict_resolutions": version.conflict_resolutions,
            "instructions": version.instructions}))
    db.commit()
    result = public_version(version)
    request.app.state.moodboard_runner.submit(version.id)
    return result


@router.patch("/{board_id}/versions/{version_id}/review")
def review(project_id: str, board_id: str, version_id: str, data: ReviewRequest, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id, write=True)
    version = require_version(db, board_id, version_id, lock=True)
    check_revision(version, data.revision)
    if version.job_status not in {"succeeded", "partial"} or version.review_status == "approved":
        problem(409, "invalid_state", "Hasil belum siap atau versi sudah disetujui")
    findings = copy.deepcopy(version.findings)
    by_id = {f["id"]: f for f in findings}
    if len({d.finding_id for d in data.decisions}) != len(data.decisions):
        problem(400, "validation_error", "Keputusan temuan duplikat")
    for decision in data.decisions:
        finding = by_id.get(decision.finding_id)
        if finding is None:
            problem(400, "unknown_finding", "ID temuan tidak ditemukan")
        finding.update(review_state=decision.decision, strength=decision.strength, note=decision.note)
        finding["reviewed_value"] = decision.value if decision.decision == "edited" else finding["original_value"]
        if decision.decision == "edited":
            finding["dasar"] = "instruksi_pengguna"
    conflicts = version.original_result["perbedaan_atau_konflik"]
    resolutions = copy.deepcopy(version.conflict_resolutions)
    for index, note in data.conflict_resolutions.items():
        if not index.isdigit() or str(int(index)) != index or int(index) >= len(conflicts) or not note.strip():
            problem(400, "validation_error", "Resolusi konflik harus memakai index valid dan catatan tidak kosong")
        resolutions[index] = note.strip()
    version.findings, version.conflict_resolutions = findings, resolutions
    if data.instructions is not None:
        version.instructions = [i.model_dump() for i in data.instructions]
    try:
        result = reviewed_summary(version)
        validate_source_links(result, version.snapshot["sources"])
    except (ValueError, KeyError, TypeError):
        db.rollback()
        problem(400, "invalid_review", "Bentuk nilai koreksi atau referensinya tidak valid")
    # Use corrected evidence in constraints, not the outdated original reference list.
    for finding in findings:
        value = finding["reviewed_value"]
        if isinstance(value, dict) and "referensi" in value:
            finding["referensi"] = value["referensi"]
    version.findings = copy.deepcopy(findings)
    version.reviewed_result = result
    version.revision += 1
    db.add(ReviewEvent(version_id=version.id, event_type="review", payload=data.model_dump()))
    db.commit()
    return public_version(version)


@router.post("/{board_id}/versions/{version_id}/approve")
def approve(project_id: str, board_id: str, version_id: str, data: ApprovalRequest, db: Session = Depends(get_db)):
    board = require_board(db, project_id, board_id, write=True)
    version = require_version(db, board_id, version_id, lock=True)
    check_revision(version, data.revision)
    if version.job_status != "succeeded" or version.review_status == "approved":
        problem(409, "invalid_state", "Versi belum siap atau sudah disetujui")
    if any(f["review_state"] == "pending" for f in version.findings):
        problem(409, "pending_review", "Semua temuan harus direview")
    if any(str(i) not in version.conflict_resolutions for i in range(len(version.original_result["perbedaan_atau_konflik"]))):
        problem(409, "unresolved_conflicts", "Selesaikan konflik atau nyatakan tetap unknown")
    version.review_status = "approved"
    version.approved_at = datetime.now(timezone.utc)
    version.reviewed_result = reviewed_summary(version)
    version.revision += 1
    board.latest_approved_version_id = version.id
    board.revision += 1
    db.add(ReviewEvent(version_id=version.id, event_type="approval", payload={"revision": data.revision}))
    db.commit()
    return public_version(version)


@router.get("/{board_id}/versions/{version_id}/events")
def review_events(project_id: str, board_id: str, version_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    require_version(db, board_id, version_id)
    events = db.scalars(select(ReviewEvent).where(ReviewEvent.version_id == version_id).order_by(ReviewEvent.created_at))
    return {"items": [{"id": e.id, "actor": e.actor, "event_type": e.event_type, "payload": e.payload,
                       "created_at": e.created_at} for e in events]}


@router.post("/{board_id}/versions/{version_id}/exports", status_code=201)
def create_export(project_id: str, board_id: str, version_id: str, data: ExportRequest,
                  key: str | None = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    key = idempotency_key(key)
    board = require_board(db, project_id, board_id)
    version = require_version(db, board_id, version_id)
    if version.review_status != "approved":
        problem(409, "not_approved", "Ekspor final hanya untuk versi disetujui")
    existing = db.scalar(select(MoodboardExport).where(MoodboardExport.version_id == version_id,
                                                     MoodboardExport.idempotency_key == key))
    if existing:
        if existing.language != data.language:
            problem(409, "idempotency_conflict", "Key telah dipakai untuk bahasa berbeda")
        return export_preview(existing)
    summary = version.reviewed_result
    instructions, constraints = None, None
    if data.language == "en":
        try:
            provider = VisionProvider()
            translated = provider.translate(summary)
            validate_source_links(translated, version.snapshot["sources"])
            validate_translation(summary, translated)
            constraints = [{"id": f["id"], "strength": f["strength"], "text": text_value(f["reviewed_value"]),
                            "references": f["referensi"]} for f in version.findings if f["review_state"] != "rejected"]
            texts = [c["text"] for c in constraints] + [i["text"] for i in version.instructions]
            translated_texts = provider.translate_texts(texts)
            for c, text in zip(constraints, translated_texts):
                c["text"] = text
            instructions = [{**i, "text": text} for i, text in zip(version.instructions, translated_texts[len(constraints):])]
            summary = translated
        except (ProviderError, ValueError) as exc:
            problem(502, "translation_failed", "Terjemahan gagal atau berubah struktur. Coba lagi.")
    timestamp = datetime.now(timezone.utc)
    content = render_markdown(board, version, summary, data.language, timestamp.isoformat(), instructions, constraints)
    slug = re.sub(r"[^a-z0-9]+", "-", version.snapshot["title"].lower()).strip("-")[:80] or "moodboard"
    export = MoodboardExport(version_id=version_id, idempotency_key=key, language=data.language,
        status="pending_confirmation" if data.language == "en" else "ready", content=content,
        content_hash=content_hash(content), filename=f"{slug}-v{version.version_number}-{data.language}.md")
    db.add(export)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(MoodboardExport).where(MoodboardExport.version_id == version_id,
                                                         MoodboardExport.idempotency_key == key))
        if existing is None or existing.language != data.language:
            problem(409, "idempotency_conflict", "Request ekspor bertabrakan")
        return export_preview(existing)
    db.refresh(export)
    return export_preview(export)


@router.get("/{board_id}/exports/{export_id}/preview")
def preview_export(project_id: str, board_id: str, export_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    export = MoodboardRepository(db).export(board_id, export_id)
    if export is None:
        problem(404, "not_found", "Ekspor tidak ditemukan")
    return export_preview(export)


@router.post("/{board_id}/exports/{export_id}/confirm")
def confirm_export(project_id: str, board_id: str, export_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    export = MoodboardRepository(db).export(board_id, export_id)
    if export is None:
        problem(404, "not_found", "Ekspor tidak ditemukan")
    if export.status != "ready":
        export.status = "ready"
        db.add(ReviewEvent(version_id=export.version_id, event_type="translation_confirmed", payload={"export_id": export.id}))
        db.commit()
    return export_preview(export)


@router.get("/{board_id}/exports/{export_id}")
def download_export(project_id: str, board_id: str, export_id: str, db: Session = Depends(get_db)):
    require_board(db, project_id, board_id)
    export = MoodboardRepository(db).export(board_id, export_id)
    if export is None:
        problem(404, "not_found", "Ekspor tidak ditemukan")
    if export.status != "ready":
        problem(409, "translation_not_confirmed", "Review preview terjemahan lalu konfirmasi sebelum mengunduh")
    return Response(export.content.encode("utf-8"), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"',
                 "X-Content-Type-Options": "nosniff", "ETag": f'"{export.content_hash}"'})
