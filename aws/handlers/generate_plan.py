"""generate-plan Lambda — triggered by SQS, calls services.process_care_plan
(atomic claim + LLM call + write-back). This is the SAME function the local Celery worker calls."""

import json

from careplan import services
from careplan.db import Base, SessionLocal, engine

Base.metadata.create_all(engine)


def lambda_handler(event, context):
    db = SessionLocal()
    try:
        for record in event.get("Records", []):
            careplan_id = json.loads(record["body"])["careplan_id"]
            ok = services.process_care_plan(db, careplan_id)  # same logic as the local worker
            print(("done " if ok else "skipped ") + str(careplan_id))
        return {"status": "done"}
    finally:
        db.close()
