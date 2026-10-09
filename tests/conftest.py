import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
import app.main as main_module
from app.modules.moodboards.service import AnalysisRunner

TEST_URL = settings.test_database_url

engine = create_engine(TEST_URL, pool_pre_ping=True)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_projects():
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM moodboard_exports"))
        conn.execute(text("DELETE FROM moodboard_review_events"))
        conn.execute(text("DELETE FROM moodboard_versions"))
        conn.execute(text("DELETE FROM moodboard_sources"))
        conn.execute(text("DELETE FROM moodboards"))
        conn.execute(text("DELETE FROM project_briefs"))
        conn.execute(text("DELETE FROM source_documents"))
        conn.execute(text("DELETE FROM shots"))
        conn.execute(text("DELETE FROM projects"))
        conn.commit()


@pytest.fixture
def client(monkeypatch):
    # Startup and recovery also use the test DB, never production.
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "AnalysisRunner", lambda: AnalysisRunner(session_factory=TestSession))
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
