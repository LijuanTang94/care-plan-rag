"""Routing layer (called views in Django).

Responsible only for: take the HTTP request -> call the service to do the work
-> use a schema to format the result -> return it. This file does NOT contain
business logic (that's in services.py) or data-format details (that's in
schemas.py). Rule of thumb: swap the frontend framework and this file wouldn't
need to change.
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from sqlalchemy.orm import Session

from careplan import services
from careplan.adapters import get_adapter
from careplan.db import get_db
from careplan.tasks import process_careplan  # local enqueueing via Celery (replaced by SQS on AWS)
from careplan.exceptions import BaseAppException
from careplan.internal_order import InternalOrder
from careplan.schemas import (
    OrderAck, OrderDetail, OrderIn, OrderStatus, PatientIn, PatientUpdate,
    ProviderIn, validate_order_input, validate_patient, validate_provider,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("care-plan")

app = FastAPI(title="Care Plan Generator")

# The schema is managed by Alembic migrations (the container runs `alembic upgrade head`
# on startup; see docker-compose).
# We no longer use create_all -- it can't alter the structure of existing tables
# (the add-a-column gotcha).

# Monitoring:
# 1) Automatically expose HTTP metrics at /metrics -- request volume, latency,
#    error rate (performance + error metrics)
Instrumentator().instrument(app).expose(app)
# 2) Custom business metric: how many care plans were generated, broken down by
#    source (cvs/clinic_b/pharmacorp)
care_plans_created = Counter(
    "care_plans_created_total", "Number of care plans created", ["source"]
)


# Unified error handler: keys off the single BaseAppException base class and turns
# any subclass into the same JSON format. Views just raise and don't care about the
# response format. Want to change the format? Change it in this one place.
@app.exception_handler(BaseAppException)
def app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


# API key auth: all /api/ endpoints must carry a correct X-API-Key header, else 401.
# Only enabled when the API_KEY environment variable is set (if unset, requests pass
# through, which is handy for running bare locally; always set it in production/containers).
@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        expected = os.environ.get("API_KEY")
        if expected and request.headers.get("X-API-Key") != expected:
            return JSONResponse(
                status_code=401,
                content={"type": "auth", "code": "INVALID_API_KEY",
                         "message": "Missing or invalid X-API-Key"},
            )
    return await call_next(request)


@app.post("/api/v1/orders", response_model=OrderAck)
def create_order(order_in: OrderIn, db: Session = Depends(get_db)) -> OrderAck:
    """CVS web form. OrderIn is already our naming, so just convert it to an InternalOrder."""
    internal = InternalOrder(**order_in.model_dump())
    validate_order_input(internal)                   # validate (schema layer)
    order = services.create_order(db, internal)      # business + duplicate detection (service layer)
    process_careplan.delay(order.care_plan.id)       # enqueue (routing layer's job; the service doesn't handle transport)
    care_plans_created.labels(source="cvs").inc()    # business metric +1
    return OrderAck.from_order(order)                # format (schema layer)


@app.post("/api/v1/intake/{source}", response_model=OrderAck)
async def intake(source: str, request: Request, confirm: bool = False,
                 db: Session = Depends(get_db)) -> OrderAck:
    """External data-source intake (clinic JSON / pharma XML).

    The adapter translates each source's format into an InternalOrder, after which
    it follows the exact same logic as the web form -- validation, duplicate
    detection, and generation are all written once. Adding a data source means
    just adding one adapter; this function doesn't change.
    """
    body = await request.body()
    internal = get_adapter(source).transform(body)   # translate into the internal canonical format
    internal.confirm = confirm
    validate_order_input(internal)                    # same validation
    order = services.create_order(db, internal)       # same business logic
    process_careplan.delay(order.care_plan.id)        # enqueue
    care_plans_created.labels(source=source).inc()    # business metric +1 (by source)
    return OrderAck.from_order(order)


class KnowledgeIn(BaseModel):
    source: str
    content: str


@app.post("/api/v1/knowledge", status_code=202)
def ingest_knowledge(body: KnowledgeIn) -> dict:
    """Store the document in object storage (MinIO/S3), then publish its key to Kafka. Returns 202
    immediately; a consumer fetches the object and indexes it into pgvector + Elasticsearch."""
    from careplan.ingestion import publish_document
    from careplan.object_store import put_document
    key = put_document(body.source, body.content)   # large blob -> object store (claim-check pattern)
    publish_document(body.source, key)               # Kafka message carries only the reference
    return {"status": "accepted", "source": body.source, "object_key": key}


@app.get("/api/v1/orders/{order_id}", response_model=OrderDetail)
def get_order(order_id: int, db: Session = Depends(get_db)) -> OrderDetail:
    order = services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderDetail.from_order(order)


@app.get("/api/v1/orders/{order_id}/status", response_model=OrderStatus)
def get_order_status(order_id: int, db: Session = Depends(get_db)) -> OrderStatus:
    """Lightweight status query: used by client polling."""
    order = services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderStatus.from_order(order)


# ===================== RESTful API =====================

def _order_brief(o):
    cp = o.care_plan
    return {
        "id": o.id,
        "patient_name": f"{o.patient.first_name} {o.patient.last_name}",
        "medication_name": o.medication_name,
        "status": cp.status if cp else "pending",
        "created_at": o.created_at.isoformat(),
    }


def _patient_brief(p):
    return {"id": p.id, "first_name": p.first_name, "last_name": p.last_name,
            "mrn": p.mrn, "dob": p.dob}


# Exercise 0 (required): order list, pagination + filtering
@app.get("/api/v1/orders")
def list_orders(page: int = 1, page_size: int = 20, status: str | None = None,
                patient_name: str | None = None, db: Session = Depends(get_db)) -> dict:
    count, orders = services.list_orders(db, page, page_size, status, patient_name)
    return {"count": count, "page": page, "page_size": page_size,
            "results": [_order_brief(o) for o in orders]}


# ---- Patient CRUD (Tickets 1-5) ----
@app.post("/api/v1/patients", status_code=201)
def create_patient(p: PatientIn, db: Session = Depends(get_db)) -> dict:
    validate_patient(p)
    patient = services.create_patient(db, p.first_name, p.last_name, p.mrn, p.dob)
    return _patient_brief(patient)


@app.get("/api/v1/patients")
def list_patients(page: int = 1, page_size: int = 20, search: str | None = None,
                  db: Session = Depends(get_db)) -> dict:
    count, patients = services.list_patients(db, page, page_size, search)
    return {"count": count, "page": page, "page_size": page_size,
            "results": [_patient_brief(p) for p in patients]}


@app.get("/api/v1/patients/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db)) -> dict:
    p = services.get_patient(db, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    orders = services.get_patient_orders(db, patient_id)
    return {**_patient_brief(p), "orders": [_order_brief(o) for o in orders]}


@app.put("/api/v1/patients/{patient_id}")
def update_patient(patient_id: int, body: PatientUpdate, db: Session = Depends(get_db)) -> dict:
    p = services.update_patient(db, patient_id, body.first_name, body.last_name, body.dob)
    if p is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return _patient_brief(p)


@app.delete("/api/v1/patients/{patient_id}", status_code=204)
def delete_patient(patient_id: int, db: Session = Depends(get_db)) -> Response:
    ok = services.delete_patient(db, patient_id)  # raises BlockError (409) if there are active orders
    if not ok:
        raise HTTPException(status_code=404, detail="Patient not found")
    return Response(status_code=204)


@app.get("/api/v1/patients/{patient_id}/orders")
def patient_orders(patient_id: int, db: Session = Depends(get_db)) -> dict:
    p = services.get_patient(db, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    orders = services.get_patient_orders(db, patient_id)
    return {"patient_id": p.id, "patient_name": f"{p.first_name} {p.last_name}",
            "orders": [_order_brief(o) for o in orders]}


# ---- Provider (Ticket 6) ----
@app.post("/api/v1/providers", status_code=201)
def create_provider(p: ProviderIn, db: Session = Depends(get_db)) -> dict:
    validate_provider(p)
    prov = services.create_provider(db, p.name, p.npi)
    return {"id": prov.id, "name": prov.name, "npi": prov.npi}


# ---- Download care plan (Ticket 10) ----
@app.get("/api/v1/orders/{order_id}/careplan/download")
def download_careplan(order_id: int, db: Session = Depends(get_db)):
    order = services.get_order(db, order_id)
    cp = order.care_plan if order else None
    if cp is None or cp.status != "completed":      # only a completed plan can be downloaded
        raise HTTPException(status_code=404, detail="CarePlan not yet generated")
    return PlainTextResponse(
        cp.content,
        headers={"Content-Disposition": f'attachment; filename="careplan_order_{order_id}.txt"'},
    )


# ---- Retry on failure (Ticket 11) ----
@app.post("/api/v1/orders/{order_id}/retry", status_code=202)
def retry_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    order = services.retry_order(db, order_id)      # raises BlockError (409) if not failed
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    process_careplan.delay(order.care_plan.id)      # re-enqueue
    return {"order_id": order.id, "status": "processing",
            "message": "CarePlan generation restarted"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Frontend page (form + polling)."""
    html = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Care Plan Generator</title>
<style>
 :root{--bg:#ffffff;--card:#fff;--ink:#1f2d3d;--muted:#6b7c8f;--accent:#0e7490;--accent-d:#0b5563;--line:#dfe6ea}
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:2rem 1rem;line-height:1.5}
 .wrap{max-width:720px;margin:0 auto}
 header h1{margin:0;font-size:1.5rem;display:flex;align-items:center;gap:.5rem}
 header .badge{background:var(--accent);color:#fff;border-radius:6px;font-size:.68rem;padding:.15rem .45rem;font-weight:700;letter-spacing:.04em}
 header p{margin:.35rem 0 1.2rem;color:var(--muted);font-size:.9rem}
 .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1.5rem;box-shadow:0 1px 3px rgba(16,40,60,.06)}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:.85rem 1rem}
 .full{grid-column:1/-1}
 label{display:block;margin-bottom:.25rem;font-size:.74rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
 label .hint{font-weight:400;text-transform:none;letter-spacing:0;color:#9aa9b8}
 input,textarea{width:100%;padding:.55rem .65rem;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fbfdfe}
 input:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(14,116,144,.12)}
 button{margin-top:1.25rem;padding:.7rem 1.4rem;font-size:.95rem;font-weight:600;color:#fff;background:var(--accent);border:none;border-radius:8px;cursor:pointer}
 button:hover{background:var(--accent-d)}
 #status{margin:1rem 0 0;font-size:.9rem;color:var(--muted);min-height:1.2rem}
 #result:empty{display:none}
 pre{white-space:pre-wrap;background:#f6f9fa;border:1px solid var(--line);padding:1rem;border-radius:8px;margin-top:1rem;font-size:.85rem}
 footer{color:#9aa9b8;font-size:.75rem;text-align:center;margin-top:1.25rem}
</style></head>
<body>
<div class="wrap">
<header>
 <h1>Care Plan Generator <span class="badge">RAG</span></h1>
 <p>Enter patient clinical details &rarr; validated &amp; de-duplicated &rarr; retrieval-grounded LLM care plan.</p>
</header>
<div class="card">
<form id="f">
 <div class="grid">
  <div><label>First name</label><input name="patient_first_name" value="A." required></div>
  <div><label>Last name</label><input name="patient_last_name" value="B." required></div>
  <div><label>Referring provider</label><input name="referring_provider" value="Dr. Smith" required></div>
  <div><label>Provider NPI <span class="hint">(10 digits)</span></label><input name="referring_provider_npi" value="1234567890" inputmode="numeric" pattern="\\d{10}" maxlength="10" title="NPI must be exactly 10 digits" required></div>
  <div><label>Patient MRN <span class="hint">(6 digits)</span></label><input name="patient_mrn" value="000123" inputmode="numeric" pattern="\\d{6}" maxlength="6" title="MRN must be exactly 6 digits" required></div>
  <div><label>Patient DOB</label><input type="date" name="patient_dob" value="1979-06-08" required></div>
  <div><label>Primary diagnosis <span class="hint">(ICD-10)</span></label><input name="primary_diagnosis" value="G70.00" required></div>
  <div><label>Medication</label><input name="medication_name" value="IVIG" required></div>
  <div class="full"><label>Patient records</label><textarea name="patient_records" rows="4" required>Generalized myasthenia gravis (AChR antibody positive). Neurology recommends IVIG.</textarea></div>
 </div>
 <button type="submit">Generate Care Plan</button>
</form>
<p id="status"></p>
<div id="confirmBox"></div>
<pre id="result"></pre>
</div>
<footer>Async pipeline &middot; pgvector RAG &middot; Claude / OpenAI &middot; demo UI</footer>
</div>
<script>
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');
const confirmEl = document.getElementById('confirmBox');
// For the demo only: a real frontend should obtain a token via user login and never
// embed the key in the page (this is purely for demonstration)
const API_KEY = "__API_KEY__";

async function submitOrder(confirm) {
  const data = Object.fromEntries(new FormData(document.getElementById('f')).entries());
  data.confirm = confirm;                       // the second submit sends confirm=true to skip the warning
  confirmEl.innerHTML = '';
  resultEl.textContent = '';
  statusEl.textContent = 'Submitting...';

  const res = await fetch('/api/v1/orders', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-API-Key': API_KEY},
    body: JSON.stringify(data),
  });
  const d = await res.json();

  if (d.type === 'warning') {                   // 200 + warning: show a confirm button
    statusEl.textContent = '⚠️ ' + d.message;
    const btn = document.createElement('button');
    btn.textContent = 'Confirm and continue';
    btn.onclick = () => submitOrder(true);       // resubmit with confirm=true
    confirmEl.appendChild(btn);
    return;
  }
  if (!res.ok) {                                 // 400 validation / 409 block
    statusEl.textContent = '❌ ' + d.message;
    return;
  }

  // Success: start polling
  let tries = 0;
  const poll = async () => {
    tries++;
    const r = await fetch('/api/v1/orders/' + d.id + '/status', {headers: {'X-API-Key': API_KEY}});
    const s = await r.json();
    statusEl.textContent = 'Order ' + d.id + ' · status: ' + s.status + ' · polled ' + tries + ' time(s)';
    if (s.status === 'completed') resultEl.textContent = s.care_plan;
    else if (s.status === 'failed') resultEl.textContent = '❌ Generation failed, please retry';
    else setTimeout(poll, 3000);
  };
  poll();
}

document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  submitOrder(false);
});
</script>
</body></html>"""
    return html.replace("__API_KEY__", os.environ.get("API_KEY", ""))
