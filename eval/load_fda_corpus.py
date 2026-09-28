"""Load the FDA label corpus through the real ingestion path and time it.

Each (drug, section) becomes one document "FDA label: <drug> — <section>", POSTed to
/api/v1/knowledge: bytes go to MinIO, only the key goes to Kafka, and the ingestion consumer
chunks, embeds and indexes it into pgvector + Elasticsearch. The script then waits until every
document is indexed and reports wall-clock time.

    docker compose exec app python -m eval.load_fda_corpus
"""

import gzip
import json
import os
import time
import urllib.request
from pathlib import Path

from sqlalchemy import text

from careplan.db import SessionLocal
from careplan.ingestion import consumer_lag

CORPUS = Path(__file__).parent / "data" / "fda_labels.jsonl.gz"
API = os.environ.get("CAREPLAN_API", "http://localhost:8000")
PREFIX = "FDA label: "


def source_name(drug: str, section: str) -> str:
    return f"{PREFIX}{drug} — {section}"


def documents() -> list[tuple[str, str]]:
    """One document per label section; brand names from the label's openFDA metadata lead each one,
    since the label text itself rarely says "Zocor" when it means simvastatin."""
    with gzip.open(CORPUS, "rt", encoding="utf-8") as f:
        drugs = [json.loads(line) for line in f]
    docs = []
    for d in drugs:
        brands = f"{d['drug']} is marketed as {', '.join(d['brand_names'])}.\n\n" if d["brand_names"] else ""
        docs += [(source_name(d["drug"], s), brands + t) for s, t in d["sections"].items()]
    return docs


def post(source: str, content: str) -> None:
    req = urllib.request.Request(
        f"{API}/api/v1/knowledge",
        data=json.dumps({"source": source, "content": content}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": os.environ.get("API_KEY", "")},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 202, r.status


def indexed(db) -> tuple[int, int]:
    """(documents, chunks) from the FDA corpus currently in pgvector."""
    row = db.execute(text("SELECT count(DISTINCT source), count(*) FROM knowledge_chunks "
                          "WHERE source LIKE :p"), {"p": PREFIX + "%"}).one()
    return row[0], row[1]


def wait_until_indexed(started: float, timeout_s: int = 3600) -> tuple[int, int]:
    """Block until the indexer group has committed every message (also correct for a re-load,
    where all documents already exist and only their content changes)."""
    db = SessionLocal()
    try:
        while time.time() - started < timeout_s:
            lag = consumer_lag()
            docs, chunks = indexed(db)
            db.commit()
            print(f"  {time.time() - started:6.0f}s  lag {lag} messages; {docs} documents / {chunks} chunks indexed")
            if lag == 0:
                return docs, chunks
            time.sleep(15)
        raise TimeoutError(f"consumer still lagging after {timeout_s}s")
    finally:
        db.close()


def main() -> None:
    docs = documents()
    print(f"publishing {len(docs)} documents via {API}/api/v1/knowledge")
    started = time.time()
    for source, content in docs:
        post(source, content)
    published = time.time() - started
    print(f"published in {published:.0f}s; waiting for the ingestion consumer")
    n_docs, n_chunks = wait_until_indexed(started)
    total = time.time() - started
    print(f"indexed {n_docs} documents / {n_chunks} chunks in {total:.0f}s "
          f"({n_chunks / total:.0f} chunks/s end to end)")


if __name__ == "__main__":
    main()
