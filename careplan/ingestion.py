"""Kafka knowledge-ingestion pipeline (decoupled + replayable).

Why Kafka here, not just Celery: the knowledge base needs live document ingestion, and a
durable log gives three things a task queue doesn't:
  - replay: change the embedding model or chunking, then re-consume the topic from offset 0
    to rebuild the entire index from the durable log;
  - multiple consumer groups: the same document stream can fan out to pgvector, ES, analytics;
  - durability: documents survive an indexer outage and get processed on recovery.

Flow:  POST /api/v1/knowledge -> store blob in object storage -> publish_document(key) ->
       topic `knowledge-ingestion` -> run_consumer() -> fetch blob by key -> rag.ingest()
       (chunk -> embed -> pgvector + Elasticsearch).

Delivery is at-least-once: the producer waits for acks=all, and the consumer commits its
offset only AFTER indexing succeeds (so a crash mid-index re-processes, never drops).
"""

import json
import logging
import os
from functools import lru_cache

logger = logging.getLogger("care-plan")

TOPIC = "knowledge-ingestion"


def _bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")


@lru_cache
def get_producer():
    from kafka import KafkaProducer

    return KafkaProducer(
        bootstrap_servers=_bootstrap(),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",   # wait until the broker has persisted the record -> at-least-once durability
        retries=3,
    )


def publish_document(source: str, object_key: str) -> None:
    """Publish a document-ingestion event carrying only the object-store key (claim-check).
    Blocks until the broker acks so the API can honestly report success, not fire-and-forget."""
    get_producer().send(TOPIC, {"source": source, "object_key": object_key}).get(timeout=10)
    logger.info("published document event source=%s key=%s", source, object_key)


def run_consumer() -> None:
    """Consume document events and index them (chunk -> embed -> pgvector + ES)."""
    from kafka import KafkaConsumer

    from careplan import object_store, rag
    from careplan.db import SessionLocal

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=_bootstrap(),
        group_id="knowledge-indexer",
        enable_auto_commit=False,        # commit only after a successful write (at-least-once)
        auto_offset_reset="earliest",    # a fresh group replays the whole log
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )
    logger.info("knowledge-indexer consuming topic=%s", TOPIC)
    for msg in consumer:
        doc = msg.value
        db = SessionLocal()
        try:
            content = object_store.get_document(doc["object_key"])   # fetch the blob referenced by the message
            n = rag.ingest(db, doc["source"], content)
            consumer.commit()            # advance the offset only after indexing succeeded
            logger.info("indexed %d chunks from %s (offset %d committed)", n, doc["source"], msg.offset)
        except Exception:
            logger.exception("indexing failed for %s; offset NOT committed (will re-process)", doc.get("source"))
        finally:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_consumer()
