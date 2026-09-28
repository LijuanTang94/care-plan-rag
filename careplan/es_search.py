"""Elasticsearch hybrid retrieval: BM25 (lexical) + kNN (dense vector), fused with RRF.

Why add ES on top of pgvector:
  - pgvector alone is pure *semantic* search. BM25 adds *lexical* matching, which catches
    exact terms, IDs, drug names, and rare tokens that dense vectors tend to miss.
  - We run BOTH signals and fuse their rankings with Reciprocal Rank Fusion (RRF): a chunk
    that ranks well in *either* signal surfaces. RRF fuses by rank, so the two score scales
    (BM25 vs. cosine) don't have to be normalized -- more robust than adding raw scores.

Toggled by env RETRIEVAL_BACKEND=es (otherwise rag.py stays on pgvector). ES_URL points at
the cluster. The index mirrors knowledge_chunks: a `content` text field for BM25 and a
384-dim `embedding` dense_vector for kNN.
"""

import logging
import os
from functools import lru_cache

from careplan.embedding_service import DIM

logger = logging.getLogger("care-plan")

INDEX = "knowledge_chunks"


@lru_cache
def get_es():
    """Cached Elasticsearch client. Imported lazily so the dependency is only needed when ES is on."""
    from elasticsearch import Elasticsearch

    url = os.environ.get("ES_URL", "http://localhost:9200")
    return Elasticsearch(url, request_timeout=10)


def ensure_index() -> None:
    """Create the index if missing (idempotent): a BM25 text field + a cosine dense_vector field."""
    es = get_es()
    if es.indices.exists(index=INDEX):
        return
    es.indices.create(
        index=INDEX,
        mappings={
            "properties": {
                "source": {"type": "keyword"},
                # english analyzer: drops stopwords and stems, so "who should not take X" scores on X
                "content": {"type": "text", "analyzer": "english"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": DIM,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    )
    logger.info("created ES index %s", INDEX)


def index_chunks(source: str, chunks: list[str], vecs: list[list[float]]) -> None:
    """Bulk-index chunks + their vectors into ES, replacing any earlier copy of `source`
    (mirrors the pgvector ingest path)."""
    from elasticsearch.helpers import bulk

    ensure_index()
    get_es().delete_by_query(index=INDEX, query={"term": {"source": source}}, refresh=True)
    actions = [
        {"_index": INDEX, "_id": f"{source}#{i}",
         "_source": {"source": source, "content": ch, "embedding": v}}
        for i, (ch, v) in enumerate(zip(chunks, vecs))
    ]
    # refresh=True so freshly-ingested chunks are immediately searchable (fine at ingest scale)
    bulk(get_es(), actions, refresh=True)
    logger.info("indexed %d chunks into ES from %s", len(chunks), source)


def _rrf(rank_lists: list[list[str]], k_const: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: score(doc) = sum over signals of 1/(k_const + rank).
    Combines BM25 and kNN rankings without needing their scores on the same scale."""
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for rank, doc_id in enumerate(ranks):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k_const + rank)
    return scores


def _bm25_hits(query: str, size: int) -> list[dict]:
    return get_es().search(
        index=INDEX,
        size=size,
        query={"match": {"content": query}},
        _source=["source", "content"],
    )["hits"]["hits"]


def _knn_hits(qvec: list[float], size: int) -> list[dict]:
    return get_es().search(
        index=INDEX,
        size=size,
        knn={"field": "embedding", "query_vector": qvec, "k": size, "num_candidates": max(100, size * 2)},
        _source=["source", "content"],
    )["hits"]["hits"]


def _as_chunks(hits: list[dict]) -> list[dict]:
    return [{"source": h["_source"]["source"], "content": h["_source"]["content"]} for h in hits]


def bm25_search(query: str, k: int = 3) -> list[dict]:
    """Lexical-only retrieval (used by the retrieval ablation)."""
    return _as_chunks(_bm25_hits(query, k))


def knn_search(qvec: list[float], k: int = 3) -> list[dict]:
    """Dense-only retrieval (used by the retrieval ablation)."""
    return _as_chunks(_knn_hits(qvec, k))


def hybrid_search(query: str, qvec: list[float], k: int = 3) -> list[dict]:
    """Run BM25 and kNN separately, fuse with RRF, return the top-k chunks: [{source, content}]."""
    pool = k * 5  # over-fetch from each signal so RRF has enough to fuse
    bm25 = _bm25_hits(query, pool)
    knn = _knn_hits(qvec, pool)

    docs = {h["_id"]: h["_source"] for h in bm25 + knn}
    fused = _rrf([[h["_id"] for h in bm25], [h["_id"] for h in knn]])
    top_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[:k]
    return [{"source": docs[i]["source"], "content": docs[i]["content"]} for i in top_ids]
