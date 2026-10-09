from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.database import Base, engine
from app.core.errors import error_body
from app.modules.projects import model as _projects_model  # noqa: F401 – registers ORM model
from app.modules.projects.router import router as projects_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="AI Office API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content=error_body("not_found", "Not found"),
    )


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=error_body("server_error", "An unexpected error occurred"),
    )
