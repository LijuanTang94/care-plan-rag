"""Re-ingesting a source replaces it: redelivery and topic replay must not duplicate chunks.

Needs real PostgreSQL + pgvector (knowledge_chunks uses the vector type), so it is skipped
under the SQLite unit-test setup and runs in the CI rag-eval job.
"""

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="needs PostgreSQL + pgvector",
)

SOURCE = "test: idempotent ingest"


@pytest.fixture
def db():
    from careplan.db import SessionLocal

    s = SessionLocal()
    yield s
    s.execute(text("DELETE FROM knowledge_chunks WHERE source = :s"), {"s": SOURCE})
    s.commit()
    s.close()


def _count(db) -> int:
    return db.execute(text("SELECT count(*) FROM knowledge_chunks WHERE source = :s"),
                      {"s": SOURCE}).scalar()


def test_ingesting_the_same_document_twice_keeps_one_copy(db):
    from careplan.rag import ingest

    content = "Metformin is contraindicated in severe renal impairment. " * 40
    first = ingest(db, SOURCE, content)
    second = ingest(db, SOURCE, content)

    assert first == second > 1
    assert _count(db) == first


def test_rechunked_document_leaves_no_stale_chunks(db):
    from careplan.rag import ingest

    ingest(db, SOURCE, "Long guideline text. " * 200)
    shorter = ingest(db, SOURCE, "A short replacement.")

    assert shorter == 1
    assert _count(db) == 1
