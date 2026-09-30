"""The claim lease: recovering a job whose worker died without running any cleanup.

The except-block release (test_claim_release.py) only works while the worker can still execute
code. A worker that is kill -9'd, or a Lambda that hits its timeout, leaves the plan in
"processing" with nobody to release it. The lease makes such a claim expire, and the claim time
doubles as a fencing token so a worker that was merely slow cannot overwrite the new owner.
"""

import pytest
from sqlalchemy import update

from careplan import llm_service, services, tasks
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


def _new_session():
    from careplan import main
    from careplan.db import get_db

    return next(main.app.dependency_overrides[get_db]())


@pytest.fixture
def session(client):
    db = _new_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _no_rag(monkeypatch):
    """Retrieval issues a pgvector query SQLite cannot parse; the lease does not depend on it."""
    monkeypatch.setattr(services, "retrieve", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr(services, "get_llm_service", lambda: llm_service.MockLLMService())


def _make_careplan(client) -> int:
    r = client.post("/api/v1/orders", json=base_order())
    assert r.status_code == 200
    return r.json()["careplan_id"]


def _set_claim(db, careplan_id, status, claimed_at):
    db.execute(update(CarePlan).where(CarePlan.id == careplan_id).values(status=status, claimed_at=claimed_at))
    db.commit()


def _expired():
    return services._utcnow() - services.CLAIM_LEASE - services.timedelta(seconds=1)


def test_an_expired_claim_is_taken_over(client, session):
    """A plan stranded in processing past the lease is claimed again and finished."""
    careplan_id = _make_careplan(client)
    _set_claim(session, careplan_id, "processing", _expired())

    assert services.process_care_plan(session, careplan_id) is True

    session.expire_all()
    cp = session.get(CarePlan, careplan_id)
    assert cp.status == "completed"
    assert cp.content


def test_a_live_claim_is_left_alone(client, session):
    """Within the lease the holder is presumed alive, so a duplicate delivery must skip."""
    careplan_id = _make_careplan(client)
    _set_claim(session, careplan_id, "processing", services._utcnow())

    assert services.process_care_plan(session, careplan_id) is False

    session.expire_all()
    assert session.get(CarePlan, careplan_id).status == "processing"


def test_a_processing_row_from_before_the_lease_is_recoverable(client, session):
    """Rows stuck before claimed_at existed have no claim time; treat them as expired."""
    careplan_id = _make_careplan(client)
    _set_claim(session, careplan_id, "processing", None)

    assert services.process_care_plan(session, careplan_id) is True


class _TakenOverWhileGenerating:
    """Plays a slow worker: mid-generation its lease runs out and another worker finishes the job."""

    def __init__(self, careplan_id, monkeypatch, then_raise=False):
        self.careplan_id = careplan_id
        self.monkeypatch = monkeypatch
        self.then_raise = then_raise

    def generate(self, **kwargs):
        other = _new_session()
        try:
            _set_claim(other, self.careplan_id, "processing", _expired())
            self.monkeypatch.setattr(services, "get_llm_service", lambda: llm_service.MockLLMService())
            assert services.process_care_plan(other, self.careplan_id) is True
        finally:
            other.close()
        if self.then_raise:
            raise RuntimeError("slow worker finally fails")
        return "STALE RESULT FROM THE SLOW WORKER"


def test_a_worker_that_lost_its_lease_cannot_overwrite_the_result(client, session, monkeypatch):
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(services, "get_llm_service", lambda: _TakenOverWhileGenerating(careplan_id, monkeypatch))

    assert services.process_care_plan(session, careplan_id) is False

    session.expire_all()
    cp = session.get(CarePlan, careplan_id)
    assert cp.status == "completed"
    assert cp.content != "STALE RESULT FROM THE SLOW WORKER"


def test_a_worker_that_lost_its_lease_cannot_mark_the_plan_failed(client, session, monkeypatch):
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(services, "get_llm_service", lambda: _TakenOverWhileGenerating(careplan_id, monkeypatch, then_raise=True))

    with pytest.raises(RuntimeError, match="slow worker"):
        services.process_care_plan(session, careplan_id)

    session.expire_all()
    assert session.get(CarePlan, careplan_id).status == "completed"


def test_celery_looks_again_after_the_lease_when_the_job_is_busy(client, session, monkeypatch):
    """A lost child process is requeued before its lease expires; the task must not just drop it."""
    careplan_id = _make_careplan(client)
    _set_claim(session, careplan_id, "processing", services._utcnow())
    monkeypatch.setattr(tasks, "SessionLocal", _new_session)
    scheduled = []
    monkeypatch.setattr(tasks.process_careplan, "apply_async", lambda **kw: scheduled.append(kw))

    tasks.process_careplan(careplan_id)

    assert scheduled == [{"args": [careplan_id], "countdown": services.CLAIM_LEASE.total_seconds()}]


def test_celery_does_not_reschedule_a_finished_job(client, session, monkeypatch):
    careplan_id = _make_careplan(client)
    monkeypatch.setattr(tasks, "SessionLocal", _new_session)
    scheduled = []
    monkeypatch.setattr(tasks.process_careplan, "apply_async", lambda **kw: scheduled.append(kw))

    tasks.process_careplan(careplan_id)  # completes
    tasks.process_careplan(careplan_id)  # duplicate delivery: skip, nothing to look at again

    assert scheduled == []
