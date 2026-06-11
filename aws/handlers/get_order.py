"""get-order Lambda — reuses the shared services + schemas + models (same set as the local app)."""

import json

import services
from db import Base, SessionLocal, engine
from schemas import OrderDetail

# On AWS we create tables with create_all (Alembic locally; production should run alembic as a deploy step, simplified here)
Base.metadata.create_all(engine)


def lambda_handler(event, context):
    params = event.get("pathParameters") or {}
    raw_id = params.get("id") or event.get("id")
    db = SessionLocal()
    try:
        order = services.get_order(db, int(raw_id))
        if order is None:
            return {"statusCode": 404, "body": json.dumps({"error": "order not found"})}
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": OrderDetail.from_order(order).model_dump_json(),
        }
    finally:
        db.close()
