"""RAG: pgvector extension + knowledge_chunks table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # 384 dimensions = fastembed's bge-small; change this dimension if you switch embedding models
    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            id        SERIAL PRIMARY KEY,
            source    TEXT NOT NULL,
            content   TEXT NOT NULL,
            embedding vector(384) NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_chunks")
    # Do not drop the extension (it may still be in use elsewhere)
