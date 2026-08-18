"""Regression tests for the atomic claim's failure path.

The claim commits status="processing" *before* the LLM call, so a rollback cannot
undo it. Without an explicit release, a failed generation would sit in "processing"
forever: the claim's WHERE only accepts "pending"/"failed", so no redelivery could
re-claim it, and /retry (which requires "failed") could not rescue it either.
"""

import pytest

from careplan import llm_service, services
from careplan.models import CarePlan


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


class _ExplodingLLM:
    def generate(self, **kwargs):
        raise RuntimeError("LLM is down")


@pytest.fixture
def session(client):
    """A session bound to the same in-memory database the test client uses."""
    from careplan.db import get_db
    from careplan import main

    gen = main.app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _no_rag(monkeypatch):
    """The RAG lookup issues a pgvector query (`<=>`) that SQLite cannot parse.
    These tests are about the claim's failure path, so stub retrieval out."""
    monkeypatch.setattr(services, "retrieve", lambda *a, **k: [])


def _make_careplan(client) -> int:
    r = client.post("/api/v1/orders", json=base_order())
    assert r.status_code == 200
    return r.json()["careplan_id"]


def test_failed_generation_releases_the_claim(client, session, monkeypatch):
    """A failing LLM must leave the plan in "failed", not stranded in "processing"."""
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(llm_service, "get_llm_service", lambda: _ExplodingLLM())
    monkeypatch.setattr(services, "get_llm_service", lambda: _ExplodingLLM())

    with pytest.raises(RuntimeError, match="LLM is down"):
        services.process_care_plan(session, careplan_id)

    session.expire_all()
    assert session.get(CarePlan, careplan_id).status == "failed"


def test_a_released_plan_can_be_claimed_again(client, session, monkeypatch):
    """After the release, a redelivery can re-claim and finish the work."""
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(services, "get_llm_service", lambda: _ExplodingLLM())

    with pytest.raises(RuntimeError):
        services.process_care_plan(session, careplan_id)

    # LLM recovers; the next delivery must be able to claim the "failed" plan.
    monkeypatch.setattr(services, "get_llm_service", lambda: llm_service.MockLLMService())
    assert services.process_care_plan(session, careplan_id) is True

    session.expire_all()
    cp = session.get(CarePlan, careplan_id)
    assert cp.status == "completed"
    assert cp.content


def test_retry_endpoint_works_after_a_failure(client, session, monkeypatch):
    """/retry requires status == "failed"; it must be reachable after a failed run."""
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(services, "get_llm_service", lambda: _ExplodingLLM())

    with pytest.raises(RuntimeError):
        services.process_care_plan(session, careplan_id)

    order_id = session.get(CarePlan, careplan_id).order_id
    r = client.post(f"/api/v1/orders/{order_id}/retry")
    assert r.status_code == 202, r.text

    session.expire_all()
    assert session.get(CarePlan, careplan_id).status == "pending"
