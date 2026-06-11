"""Shared pytest configuration.

Tests use a standalone in-memory SQLite database (never touching the real
postgres), with a clean database per test. They also swap Celery's .delay for a
no-op -- tests don't need a real Redis / worker / LLM.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from careplan import main
from careplan import tasks
from careplan.db import Base, get_db


@pytest.fixture
def client(monkeypatch):
    # In-memory SQLite; StaticPool lets multiple connections share one database
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    main.app.dependency_overrides[get_db] = override_get_db
    # Don't actually enqueue: replace the Celery task's .delay with a no-op
    monkeypatch.setattr(tasks.process_careplan, "delay", lambda *a, **k: None)
    # Enable API key auth; the test client sends this key by default
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("EMBED_PROVIDER", "mock")  # tests don't download the fastembed model

    with TestClient(main.app, headers={"X-API-Key": "test-key"}) as c:
        yield c

    main.app.dependency_overrides.clear()
