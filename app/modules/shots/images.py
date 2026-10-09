import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.ai_provider import ProviderError
from app.modules.projects.model import Project
from app.modules.shots.model import Shot, ShotImage, ShotRevision, ShotRevisionHead
from app.modules.shots.revisions import ensure_base, fail, require_image_approval, shot_for
from app.modules.shots.image_provider import ImageProvider, image_configuration
from app.modules.moodboards.model import Moodboard, ExtractionVersion
from app.modules.moodboards.storage import prepare_image, InvalidImage

router = APIRouter(prefix='/projects/{project_id}/shot-images', tags=['shot images'])


def image_path(key):
    root = Path(settings.shot_image_storage_dir).resolve()
    path = (root / key).resolve()
    if path.parent != root:
        raise ValueError('Invalid image storage key')
    return path


def public_image(db, row):
    revision = db.get(ShotRevision, row.revision_id)
    return {'shot_id': revision.shot_id, 'revision_id': row.revision_id, 'version_number': revision.version_number,
            'job_id': row.job_id, 'status': row.status, 'error_code': row.error_code,
            'url': f'/projects/{db.get(Shot, revision.shot_id).project_id}/shot-images/{row.revision_id}/file' if row.status == 'succeeded' else None}


def context_for(db, project_id):
    boards, keys = [], []
    for board in db.scalars(select(Moodboard).where(Moodboard.project_id == project_id, Moodboard.archived.is_(False)).order_by(Moodboard.created_at)):
        version = db.get(ExtractionVersion, board.latest_approved_version_id) if board.latest_approved_version_id else None
        if not version or version.moodboard_id != board.id or version.review_status != 'approved':
            continue
        boards.append({'id': board.id, 'version_id': version.id, 'title': board.title, 'direction': version.reviewed_result or version.original_result})
        for source in version.snapshot.get('sources', []):
            if len(keys) < 3 and source.get('included', True) and 'negative' not in source.get('roles', []) and source.get('analysis_key'):
                keys.append(source['analysis_key'])
    return {'moodboards': boards, 'reference_keys': keys}


def queue_image(db, shot, revision, context):
    require_image_approval(db, shot, revision.id)
    image = db.get(ShotImage, revision.id)
    if image and image.status in ('queued', 'running', 'succeeded'):
        return image, False
    if image is None:
        image = ShotImage(revision_id=revision.id)
        db.add(image)
    image.job_id = 'img_' + uuid.uuid4().hex
    image.status, image.error_code = 'queued', None
    image.prompt = json.dumps({'title': revision.title, 'description': revision.description, 'details': json.loads(revision.details)}, ensure_ascii=False)
    image.context = json.dumps(context, ensure_ascii=False)
    db.flush()
    return image, True


class ImageRunner:
    def __init__(self, session_factory=SessionLocal, provider=None):
        self.sessions, self.provider = session_factory, provider or ImageProvider()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='shot-image')

    def submit(self, revision_id, job_id):
        self.pool.submit(self.run, revision_id, job_id)

    def recover(self):
        with self.sessions() as db:
            rows = list(db.scalars(select(ShotImage).where(ShotImage.status.in_(['queued', 'running']))))
            for row in rows:
                if row.status == 'running':
                    row.status, row.error_code = 'failed', 'image_interrupted'
            db.commit()
            for row in rows:
                if row.status == 'queued':
                    self.submit(row.revision_id, row.job_id)

    def close(self):
        self.pool.shutdown(wait=True)

    def run(self, revision_id, job_id):
        stored = None
        try:
            with self.sessions() as db:
                revision = db.get(ShotRevision, revision_id)
                if not revision:
                    return
                shot = db.get(Shot, revision.shot_id)
                if not shot:
                    return
                shot = shot_for(db, shot.project_id, shot.id)
                require_project(db, shot.project_id, True)
                row = db.scalar(select(ShotImage).where(ShotImage.revision_id == revision_id).with_for_update())
                if not row or row.job_id != job_id or row.status != 'queued':
                    return
                require_image_approval(db, shot, revision_id)
                row.status = 'running'
                prompt, context = row.prompt, json.loads(row.context)
                db.commit()
            data = self.provider.generate(prompt, context)
            metadata, _ = prepare_image(data)
            with self.sessions() as db:
                revision = db.get(ShotRevision, revision_id)
                if not revision:
                    return
                shot = db.get(Shot, revision.shot_id)
                if not shot:
                    return
                shot = shot_for(db, shot.project_id, shot.id)
                require_project(db, shot.project_id, True)
                require_image_approval(db, shot, revision_id)
                row = db.get(ShotImage, revision_id)
                if not row or row.job_id != job_id:
                    return
                stored = 'img_' + uuid.uuid4().hex + '.image'
                path = image_path(stored)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                row.storage_key, row.mime_type = stored, metadata['mime_type']
                row.status, row.error_code = 'succeeded', None
                db.commit()
        except Exception as exc:
            if stored:
                image_path(stored).unlink(missing_ok=True)
            code = exc.code if isinstance(exc, ProviderError) else 'image_invalid_output' if isinstance(exc, InvalidImage) else 'image_generation_failed'
            if getattr(exc, 'status_code', None) == 409:
                code = 'image_approval_changed'
            with self.sessions() as db:
                row = db.get(ShotImage, revision_id)
                if row and row.job_id == job_id:
                    row.status = 'stale' if code == 'image_approval_changed' else 'failed'
                    row.error_code = code
                    db.commit()


def require_project(db, project_id, write=False):
    project = db.get(Project, project_id)
    if not project:
        fail(404, 'not_found', 'Project not found')
    if write and project.status == 'archived':
        fail(409, 'project_archived', 'Archived project cannot generate images')


@router.get('')
def list_images(project_id: str, db: Session = Depends(get_db)):
    require_project(db, project_id)
    rows = db.scalars(select(ShotImage).join(ShotRevision, ShotRevision.id == ShotImage.revision_id).join(Shot, Shot.id == ShotRevision.shot_id).where(Shot.project_id == project_id))
    return {'items': [public_image(db, row) for row in rows]}


@router.get('/config')
def image_config(project_id: str, db: Session = Depends(get_db)):
    require_project(db, project_id)
    return image_configuration()


def require_image_config():
    config = image_configuration()
    if not config['configured']:
        fail(503, 'image_not_configured', f"Isi {config['missing_key']} dan model gambar di .env backend, lalu restart backend. Lihat bagian User Manual di Shot Management.")


class ImageRequest(BaseModel):
    shot_id: str
    revision_id: str


@router.post('/generate', status_code=202)
def generate_image(project_id: str, data: ImageRequest, request: Request, db: Session = Depends(get_db)):
    require_project(db, project_id, True)
    require_image_config()
    shot = shot_for(db, project_id, data.shot_id)
    revision = require_image_approval(db, shot, data.revision_id)
    row, queued = queue_image(db, shot, revision, context_for(db, project_id))
    db.commit()
    output = public_image(db, row)
    if queued:
        request.app.state.shot_image_runner.submit(row.revision_id, row.job_id)
    return output


@router.post('/generate-approved', status_code=202)
def generate_approved(project_id: str, request: Request, db: Session = Depends(get_db)):
    require_project(db, project_id, True)
    require_image_config()
    shots = list(db.scalars(select(Shot).where(Shot.project_id == project_id, Shot.status == 'approved').order_by(Shot.id).with_for_update()))
    context, rows, jobs = context_for(db, project_id), [], []
    for shot in shots:
        head = ensure_base(db, shot)
        revision = db.get(ShotRevision, head.revision_id)
        if revision.status != 'approved':
            continue
        row, queued = queue_image(db, shot, revision, context)
        rows.append(row)
        if queued:
            jobs.append((row.revision_id, row.job_id))
    db.commit()
    output = {'queued': len(jobs), 'items': [public_image(db, row) for row in rows]}
    for revision_id, job_id in jobs:
        request.app.state.shot_image_runner.submit(revision_id, job_id)
    return output


@router.get('/{revision_id}/file')
def image_file(project_id: str, revision_id: str, db: Session = Depends(get_db)):
    revision = db.get(ShotRevision, revision_id)
    if not revision or not db.scalar(select(Shot.id).where(Shot.id == revision.shot_id, Shot.project_id == project_id)):
        fail(404, 'not_found', 'Shot image not found')
    row = db.get(ShotImage, revision_id)
    if not row or row.status != 'succeeded' or not row.storage_key or not image_path(row.storage_key).is_file():
        fail(404, 'not_found', 'Shot image is not available')
    return FileResponse(image_path(row.storage_key), media_type=row.mime_type, headers={'Cache-Control': 'private, max-age=3600'})
