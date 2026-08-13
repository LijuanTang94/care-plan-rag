"""Background generation task.

Celery supplies the parts that are tedious and easy to get subtly wrong in a hand-rolled
consumer loop: polling and idle backoff, concurrency (`--concurrency=N`), and retry with
exponential backoff (one decorator argument plus `self.retry`).

What is left here is the part that is actually domain logic, and it lives in
`services.process_care_plan` so the AWS Lambda entry point runs exactly the same code:
atomically claim the job, retrieve context, call the LLM, write the result back.
"""

import logging
import os

from celery import Celery

from careplan.db import SessionLocal
from careplan.models import CarePlan
from careplan.services import process_care_plan

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")

# Celery uses Redis as its broker (the task queue). It manages the queue, fetching, concurrency, and retries itself.
app = Celery("careplan", broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"))


@app.task(bind=True, max_retries=3)
def process_careplan(self, careplan_id: int) -> None:
    """Process one care plan. On failure, auto-retry 3 times with exponential backoff (1s, 2s, 4s); mark failed if all fail."""
    db = SessionLocal()
    try:
        # Reuse the shared logic in services (atomic claim + call LLM + write back) — same code locally and on AWS Lambda
        if process_care_plan(db, careplan_id):
            logger.info("[Celery] careplan_id=%s done", careplan_id)
        else:
            logger.info("careplan_id=%s already claimed/completed, skipping (idempotent)", careplan_id)

    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("careplan_id=%s failed (attempt %s): %s", careplan_id, self.request.retries, e)
        try:
            # Exponential backoff: wait 1s after the 0th failure, 2s after the 1st, 4s after the 2nd
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            cp = db.get(CarePlan, careplan_id)
            if cp is not None:
                cp.status = "failed"
                db.commit()
            logger.error("careplan_id=%s retries exhausted, marking failed", careplan_id)
    finally:
        db.close()
