"""Tests: happy path + bad input + duplicate detection (checked one by one against the business rules).

The focus is the error tests -- making sure invalid input is properly blocked and never quietly saved to the database.
"""


def base_order(**overrides):
    data = {
        "patient_first_name": "A.",
        "patient_last_name": "B.",
        "patient_dob": "1979-06-08",
        "referring_provider": "Dr. Smith",
        "referring_provider_npi": "1234567890",
        "patient_mrn": "000123",
        "primary_diagnosis": "G70.00",
        "medication_name": "IVIG",
        "patient_records": "mg",
    }
    data.update(overrides)
    return data


# ---------- Happy path ----------

def test_create_order_success(client):
    r = client.post("/api/v1/orders", json=base_order())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert "careplan_id" in body


def test_get_status_after_create(client):
    order_id = client.post("/api/v1/orders", json=base_order()).json()["id"]
    r = client.get(f"/api/v1/orders/{order_id}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"  # the worker is mocked out, so it stays at pending


def test_get_nonexistent_order_404(client):
    assert client.get("/api/v1/orders/9999").status_code == 404


# ---------- Input validation (400) ----------

def test_invalid_npi_returns_400(client):
    r = client.post("/api/v1/orders", json=base_order(referring_provider_npi="abc"))
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_NPI"


def test_invalid_mrn_returns_400(client):
    r = client.post("/api/v1/orders", json=base_order(patient_mrn="12"))
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_MRN"


# ---------- Business block (409) ----------

def test_provider_npi_conflict_returns_409(client):
    client.post("/api/v1/orders", json=base_order())
    # same NPI, different provider name -> must be blocked
    r = client.post("/api/v1/orders", json=base_order(
        referring_provider="Dr. Jones", patient_mrn="000999",
        patient_first_name="X.", patient_last_name="Y.", patient_dob="1990-01-01",
    ))
    assert r.status_code == 409
    assert r.json()["code"] == "PROVIDER_NPI_CONFLICT"


def test_duplicate_order_same_day_returns_409(client):
    client.post("/api/v1/orders", json=base_order())
    r = client.post("/api/v1/orders", json=base_order())  # same patient + same drug + same day
    assert r.status_code == 409
    assert r.json()["code"] == "DUPLICATE_ORDER_SAME_DAY"


# ---------- Business warning (200 + warning, skipped by confirm) ----------

def test_patient_mrn_mismatch_warning(client):
    client.post("/api/v1/orders", json=base_order())
    # same MRN, different name -> warning
    r = client.post("/api/v1/orders", json=base_order(
        patient_first_name="C.", patient_last_name="D.", medication_name="Prednisone",
    ))
    assert r.status_code == 200
    assert r.json()["type"] == "warning"
    assert r.json()["code"] == "PATIENT_MRN_MISMATCH"


def test_confirm_skips_warning(client):
    client.post("/api/v1/orders", json=base_order())
    payload = base_order(
        patient_first_name="C.", patient_last_name="D.",
        medication_name="Prednisone", confirm=True,
    )
    r = client.post("/api/v1/orders", json=payload)
    assert r.status_code == 200
    assert "careplan_id" in r.json()  # warning skipped, created successfully


# ---------- RESTful API ----------

def patient_body(**ov):
    d = {"first_name": "John", "last_name": "Smith", "mrn": "001234", "dob": "1979-06-08"}
    d.update(ov)
    return d


def test_create_patient(client):
    r = client.post("/api/v1/patients", json=patient_body())
    assert r.status_code == 201
    assert r.json()["mrn"] == "001234"


def test_create_patient_bad_mrn(client):
    r = client.post("/api/v1/patients", json=patient_body(mrn="12"))
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_MRN"


def test_list_patients_pagination(client):
    for i in range(3):
        client.post("/api/v1/patients", json=patient_body(mrn=f"00010{i}", first_name=f"P{i}"))
    b = client.get("/api/v1/patients?page=1&page_size=2").json()
    assert b["count"] == 3 and len(b["results"]) == 2  # 3 total, this page returns only 2


def test_get_patient_404(client):
    assert client.get("/api/v1/patients/999").status_code == 404


def test_create_provider(client):
    r = client.post("/api/v1/providers", json={"name": "Dr. Wilson", "npi": "1234567890"})
    assert r.status_code == 201


def test_create_provider_bad_npi(client):
    r = client.post("/api/v1/providers", json={"name": "Dr. X", "npi": "123"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_NPI"


def test_orders_list_pagination_and_filter(client):
    client.post("/api/v1/orders", json=base_order(medication_name="IVIG"))
    client.post("/api/v1/orders", json=base_order(medication_name="Prednisone", confirm=True))
    b = client.get("/api/v1/orders?page=1&page_size=20").json()
    assert b["count"] >= 2 and "results" in b
    # filter by status: the worker is mocked, so orders stay at pending
    assert client.get("/api/v1/orders?status=pending").json()["count"] >= 2
    assert client.get("/api/v1/orders?status=completed").json()["count"] == 0


def test_retry_non_failed_returns_409(client):
    oid = client.post("/api/v1/orders", json=base_order()).json()["id"]
    r = client.post(f"/api/v1/orders/{oid}/retry")
    assert r.status_code == 409  # it's pending, not failed, so it can't be retried
