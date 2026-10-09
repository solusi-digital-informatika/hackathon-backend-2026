from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy import text

from app.core.database import Base, engine
from app.core.errors import error_body
from app.core.config import settings
from app.modules.moodboards import model as _moodboards_model
from app.modules.moodboards.router import router as moodboards_router
from app.modules.moodboards.service import AnalysisRunner
from app.modules.projects import model as _projects_model  # noqa: F401 – registers ORM model
from app.modules.projects.router import router as projects_router
from app.modules.shots import model as _shots_model  # noqa: F401 – registers ORM model
from app.modules.shots.router import router as shots_router
from app.modules.brief import model as _brief_model  # noqa: F401 – registers ORM model
from app.modules.brief.router import router as brief_router
from app.modules.directions import model as _directions_model  # noqa: F401 – registers ORM model
from app.modules.directions.router import router as directions_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    Base.metadata.create_all(bind=engine)
    runner = AnalysisRunner()
    application.state.moodboard_runner = runner
    runner.recover()
    try:
        yield
    finally:
        runner.close()


app = FastAPI(title="AI Office API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(shots_router)
app.include_router(brief_router)
app.include_router(directions_router)
app.include_router(moodboards_router)


@app.exception_handler(HTTPException)
async def not_found_handler(request: Request, exc):
    detail = exc.detail if isinstance(exc.detail, dict) else {
        "code": "not_found" if exc.status_code == 404 else "request_error", "message": str(exc.detail), "fields": []}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc):
    fields = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=400, content=error_body("validation_error", "Input is invalid", fields))


@app.get("/health", tags=["health"])
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "ai_configured": bool(settings.ai_api_key and settings.ai_vision_model)}


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=error_body("server_error", "An unexpected error occurred"),
    )
