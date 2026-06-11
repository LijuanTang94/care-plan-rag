"""create-order Lambda — reuses services.create_order (validation + duplicate detection all live in there),
then sends to SQS. Does exactly what the local FastAPI route does; only the queue changes from Celery to SQS."""

import json
import os

import boto3
import services
from db import Base, SessionLocal, engine
from exceptions import BaseAppException
from internal_order import InternalOrder
from schemas import OrderAck, validate_order_input

Base.metadata.create_all(engine)
sqs = boto3.client("sqs")


def lambda_handler(event, context):
    body = event.get("body")
    if isinstance(body, str):
        data = json.loads(body)
    elif isinstance(body, dict):
        data = body
    else:
        data = event

    db = SessionLocal()
    try:
        internal = InternalOrder(
            patient_first_name=data.get("patient_first_name", ""),
            patient_last_name=data.get("patient_last_name", ""),
            patient_dob=data.get("patient_dob", ""),
            patient_mrn=data.get("patient_mrn", ""),
            referring_provider=data.get("referring_provider", ""),
            referring_provider_npi=data.get("referring_provider_npi", ""),
            primary_diagnosis=data.get("primary_diagnosis", ""),
            medication_name=data.get("medication_name", ""),
            patient_records=data.get("patient_records", ""),
            confirm=data.get("confirm", False),
        )
        validate_order_input(internal)              # same validation
        order = services.create_order(db, internal)  # same business logic + duplicate detection
        sqs.send_message(                            # enqueue (Celery locally, SQS here)
            QueueUrl=os.environ["SQS_QUEUE_URL"],
            MessageBody=json.dumps({"careplan_id": order.care_plan.id}),
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": OrderAck.from_order(order).model_dump_json(),
        }
    except BaseAppException as e:   # no FastAPI central handler here, so we turn exceptions into responses ourselves
        db.rollback()
        return {
            "statusCode": e.http_status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(e.to_dict()),
        }
    finally:
        db.close()
