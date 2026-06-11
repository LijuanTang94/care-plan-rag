"""The Celery version of the worker.

Compare it with worker.py and you'll notice:
- No while True, no BLPOP, no agonizing over "how often to poll / idle spinning" — Celery handles all of it
- No hand-rolled concurrency — pass --concurrency=N at startup and you get N concurrent workers
- Retry on failure + exponential backoff — one decorator argument + self.retry does it
You only wrote "the three business steps": query the DB → call the LLM → write back. That's "don't reinvent the wheel."

Note: Celery itself isn't an interview topic here. The point is to appreciate how much it saves you.
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
