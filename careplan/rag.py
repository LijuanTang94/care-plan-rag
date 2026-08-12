"""RAG: chunk knowledge-base documents + embed them + store them in pgvector; retrieve top-k by query.

We operate on knowledge_chunks with raw SQL (rather than putting it in the ORM models)
so that Lambda's create_all isn't affected by pgvector.
"""

import logging
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from careplan.embedding_service import get_embedder

logger = logging.getLogger("care-plan")


def _use_es() -> bool:
    """RETRIEVAL_BACKEND=es turns on Elasticsearch hybrid retrieval; anything else stays on pgvector."""
    return os.environ.get("RETRIEVAL_BACKEND", "pgvector").lower() == "es"


def _to_vec(values) -> str:
    """list[float] → pgvector literal '[v1,v2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def chunk_text(content: str, size: int = 500, overlap: int = 80) -> list[str]:
    """Simple chunking: a fixed character window with overlap.
    The overlap keeps sentences/semantics from being cut at a chunk boundary
    (interviewers like to ask about chunking strategy)."""
    content = content.strip()
    if len(content) <= size:
        return [content]
    chunks, start = [], 0
    while start < len(content):
        chunks.append(content[start:start + size])
        start += size - overlap
    return chunks


def ingest(db: Session, source: str, content: str) -> int:
    """Chunk → embed → store. Returns the number of chunks written."""
    chunks = chunk_text(content)
    vecs = get_embedder().embed(chunks)
    for ch, v in zip(chunks, vecs):
        db.execute(
            text("INSERT INTO knowledge_chunks (source, content, embedding) "
                 "VALUES (:s, :c, CAST(:e AS vector))"),
            {"s": source, "c": ch, "e": _to_vec(v)},
        )
    db.commit()
    if _use_es():
        try:
            from careplan import es_search
            es_search.index_chunks(source, chunks, vecs)
        except Exception:
            logger.exception("ES indexing failed; the pgvector copy is still written")
    logger.info("ingested %d chunks from %s", len(chunks), source)
    return len(chunks)


def retrieve(db: Session, query: str, k: int = 3) -> list[dict]:
    """Retrieve the k most relevant chunks for a query.

    With RETRIEVAL_BACKEND=es this runs ES hybrid search (BM25 + kNN, RRF-fused); on any ES
    error or empty result it falls back to pgvector cosine search. Returns [] if both are empty.
    """
    qv = get_embedder().embed_query(query)   # use embed_query for the query (bge needs the instruction prefix)
    if _use_es():
        try:
            from careplan import es_search
            hits = es_search.hybrid_search(query, qv, k)
            if hits:
                return hits
            logger.warning("ES returned no hits; falling back to pgvector")
        except Exception:
            logger.exception("ES search failed; falling back to pgvector")
    rows = db.execute(
        text("SELECT source, content FROM knowledge_chunks "
             "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"),
        {"q": _to_vec(qv), "k": k},
    ).all()
    return [{"source": r[0], "content": r[1]} for r in rows]
