"""Hand-rolled worker (a learning artifact — first feel how much you have to worry about without a framework).

What it does is exactly the flow you'd come up with yourself:
  blocking-pop a careplan_id from Redis → check whether status is pending (idempotency) → set it to processing
  → call the LLM (via llm.py here, mockable) → write back content and status=completed (or failed on error)

Note: it only writes the result to the database. Proactively notifying the frontend is out of scope here.
For now you have to refresh manually to see it.

Note: this is the hand-rolled version, and a lot is left undone (retry on failure, exponential backoff,
concurrency, crash recovery, ...). The Celery version supersedes it and handles all of that grunt work
for you; this one is kept only as a learning artifact.
"""

import logging
import os

import redis

from db import SessionLocal
from llm_service import get_llm_service
from models import CarePlan, Order, Patient, Provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# decode_responses=True: values come back as strings, so we don't have to decode bytes ourselves
queue = redis.from_url(
    os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    decode_responses=True,
)
QUEUE_KEY = "careplan_queue"


def process_one(careplan_id: int) -> None:
    db = SessionLocal()
    try:
        cp = db.get(CarePlan, careplan_id)
        if cp is None:
            logger.warning("careplan_id=%s not found in the database, skipping", careplan_id)
            return

        # Idempotency: don't reprocess anything that isn't pending (avoids paying the LLM twice)
        if cp.status != "pending":
            logger.info("careplan_id=%s has status %s, not pending, skipping", careplan_id, cp.status)
            return

        cp.status = "processing"
        db.commit()  # claim this task

        order = db.get(Order, cp.order_id)
        patient = db.get(Patient, order.patient_id)
        provider = db.get(Provider, order.provider_id)

        logger.info("starting careplan_id=%s (%s / %s)...",
                    careplan_id, f"{patient.first_name} {patient.last_name}", order.medication_name)

        text = get_llm_service().generate(
            patient_name=f"{patient.first_name} {patient.last_name}",
            mrn=patient.mrn,
            provider_name=provider.name,
            npi=provider.npi,
            diagnosis=order.primary_diagnosis,
            medication=order.medication_name,
            records=order.patient_records,
        )

        cp.content = text
        cp.status = "completed"
        db.commit()
        logger.info("careplan_id=%s done → status=completed, %d chars", careplan_id, len(text))

    except Exception as e:  # noqa: BLE001 — hand-rolled version: crude catch-all, mark failed
        db.rollback()
        cp = db.get(CarePlan, careplan_id)
        if cp is not None:
            cp.status = "failed"
            db.commit()
        logger.error("careplan_id=%s processing failed: %s", careplan_id, e)
    finally:
        db.close()


def main() -> None:
    logger.info("Worker started, blocking on queue '%s' (sleeps when empty, wakes when there's work)...", QUEUE_KEY)
    while True:
        # BLPOP: blocks and sleeps when the queue is empty (no CPU-burning spin), and wakes the instant a task arrives.
        # timeout=5: surfaces every 5 seconds so we can watch logs / shut down gracefully; set to 0 to block forever.
        item = queue.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            continue
        _, raw_id = item
        careplan_id = int(raw_id)
        logger.info("pulled careplan_id=%s from the queue", careplan_id)
        process_one(careplan_id)


if __name__ == "__main__":
    main()
