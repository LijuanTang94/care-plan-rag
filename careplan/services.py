"""Service layer: business logic + duplicate detection (the rules that hit the database).

Duplicate-detection rules (confirmed during requirements clarification):
  Provider  same NPI + same name        -> reuse
  Provider  same NPI + different name    -> BlockError 409 (NPI is nationally unique)
  Patient   same MRN + same name/DOB     -> reuse
  Patient   same MRN + different name/DOB -> Warning (possible data-entry error)
  Patient   same name+DOB + different MRN -> Warning (possibly the same person)
  Order     same patient+drug+same day    -> BlockError 409 (definitely a duplicate submission)
  Order     same patient+drug+diff day     -> Warning (possibly a refill)
When confirm=True, all Warnings are skipped (but Blocks always stop the request).
"""

import logging
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from careplan.exceptions import BlockError, WarningException
from careplan.internal_order import InternalOrder
from careplan.llm_service import get_llm_service
from careplan.models import CarePlan, Order, Patient, Provider
from careplan.rag import retrieve

logger = logging.getLogger("care-plan")


def _get_or_create_provider(db: Session, order_in: InternalOrder) -> Provider:
    existing = db.scalar(select(Provider).where(Provider.npi == order_in.referring_provider_npi))
    if existing is not None:
        if existing.name == order_in.referring_provider:
            return existing  # same NPI + same name -> reuse
        # same NPI + different name -> block (NPI is nationally unique; one side must be wrong)
        logger.error("NPI conflict: %s already belongs to '%s'", existing.npi, existing.name)
        raise BlockError(
            "This NPI already exists but under a different provider name; please verify",
            code="PROVIDER_NPI_CONFLICT",
            detail={"npi": existing.npi, "existing_name": existing.name},
        )
    provider = Provider(name=order_in.referring_provider, npi=order_in.referring_provider_npi)
    db.add(provider)
    db.flush()
    return provider


def _get_or_create_patient(db: Session, order_in: InternalOrder, confirm: bool) -> Patient:
    fn, ln, dob = order_in.patient_first_name, order_in.patient_last_name, order_in.patient_dob

    by_mrn = db.scalar(select(Patient).where(Patient.mrn == order_in.patient_mrn))
    if by_mrn is not None:
        if by_mrn.first_name == fn and by_mrn.last_name == ln and by_mrn.dob == dob:
            return by_mrn  # same MRN + same name/DOB -> reuse
        if not confirm:    # same MRN + different name/DOB -> warning
            logger.warning("MRN %s already exists but with a different identity", order_in.patient_mrn)
            raise WarningException(
                "This MRN already exists but with a different name/DOB; possible data-entry error. Continue?",
                code="PATIENT_MRN_MISMATCH",
                detail={"mrn": order_in.patient_mrn, "existing_name": f"{by_mrn.first_name} {by_mrn.last_name}"},
            )
        return by_mrn  # after confirmation: reuse the patient with this MRN

    # No MRN match: check for an existing patient with the same name and DOB (different MRN)
    by_identity = db.scalar(
        select(Patient).where(Patient.first_name == fn, Patient.last_name == ln, Patient.dob == dob)
    )
    if by_identity is not None and not confirm:
        logger.warning("Existing patient with the same name and DOB but a different MRN")
        raise WarningException(
            "A patient with the same name and DOB already exists (different MRN). Same person? Continue?",
            code="PATIENT_POSSIBLE_DUPLICATE",
            detail={"existing_mrn": by_identity.mrn},
        )

    patient = Patient(first_name=fn, last_name=ln, mrn=order_in.patient_mrn, dob=dob)
    db.add(patient)
    db.flush()
    return patient


def _check_order_duplicate(db: Session, patient: Patient, order_in: InternalOrder, confirm: bool) -> None:
    existing = db.scalars(
        select(Order).where(
            Order.patient_id == patient.id,
            Order.medication_name == order_in.medication_name,
        )
    ).all()
    if not existing:
        return
    today = datetime.now().date()
    same_day = [o for o in existing if o.created_at.date() == today]
    if same_day:  # same patient+drug+same day -> block
        logger.error("Duplicate order: same patient + same drug + same day")
        raise BlockError(
            "This patient already has an order for the same medication today; likely a duplicate submission",
            code="DUPLICATE_ORDER_SAME_DAY",
            detail={"order_id": same_day[0].id},
        )
    if not confirm:  # same patient+drug+different day -> warning (possible refill)
        logger.warning("Possible refill: same patient + same drug + different day")
        raise WarningException(
            "This patient recently had an order for the same medication; possibly a refill. Continue?",
            code="POSSIBLE_REFILL",
            detail={"previous_order_id": existing[-1].id},
        )


def create_order(db: Session, order_in: InternalOrder) -> Order:
    """Create the order + care plan (pending), generated asynchronously. Runs duplicate detection along the way."""
    confirm = order_in.confirm

    provider = _get_or_create_provider(db, order_in)
    patient = _get_or_create_patient(db, order_in, confirm)
    _check_order_duplicate(db, patient, order_in, confirm)

    order = Order(
        patient_id=patient.id,
        provider_id=provider.id,
        medication_name=order_in.medication_name,
        primary_diagnosis=order_in.primary_diagnosis,
        patient_records=order_in.patient_records,
    )
    db.add(order)
    db.flush()

    care_plan = CarePlan(order_id=order.id, content="", status="pending")
    db.add(care_plan)
    db.commit()  # persist first (keep a record)
    logger.info("Persisted (pending), order_id=%s, careplan_id=%s", order.id, care_plan.id)
    # Note: enqueueing is left to the caller (local routes use Celery.delay, AWS Lambda uses SQS).
    # The service layer doesn't depend on a specific message transport, so local and
    # Lambda can reuse the same create_order.
    return order


def get_order(db: Session, order_id: int) -> Order | None:
    return db.get(Order, order_id)


def process_care_plan(db: Session, careplan_id: int) -> bool:
    """Generate one care plan: atomically claim -> call the LLM -> write back as completed.
    The local Celery worker and the AWS generate-plan Lambda share this one function (truly one set of logic).
    Returns True if it was processed; False if skipped (already claimed/completed -- idempotent).
    """
    claimed = db.execute(
        update(CarePlan)
        .where(CarePlan.id == careplan_id, CarePlan.status.in_(["pending", "failed"]))
        .values(status="processing")
    )
    db.commit()
    if claimed.rowcount == 0:
        return False

    cp = db.get(CarePlan, careplan_id)
    order = db.get(Order, cp.order_id)
    patient = db.get(Patient, order.patient_id)
    provider = db.get(Provider, order.provider_id)

    # RAG: retrieve relevant knowledge-base material by medication+diagnosis and inject it into
    # the prompt so generation is grounded (falls back to plain generation if the base is empty)
    refs = retrieve(db, f"{order.medication_name} {order.primary_diagnosis}", k=3)
    context = "\n\n".join(f"[{r['source']}] {r['content']}" for r in refs)

    cp.content = get_llm_service().generate(
        patient_name=f"{patient.first_name} {patient.last_name}",
        mrn=patient.mrn,
        provider_name=provider.name,
        npi=provider.npi,
        diagnosis=order.primary_diagnosis,
        medication=order.medication_name,
        records=order.patient_records,
        context=context,
    )
    cp.status = "completed"
    db.commit()
    return True


# ===================== RESTful API =====================

def list_orders(db, page, page_size, status=None, patient_name=None):
    """Order list: pagination + filter by status / patient name (Exercise 0, required)."""
    q = select(Order)
    if status:                                   # filter by status (join CarePlan)
        q = q.join(CarePlan, CarePlan.order_id == Order.id).where(CarePlan.status == status)
    if patient_name:                             # fuzzy search by patient name (join Patient)
        q = q.join(Patient, Patient.id == Order.patient_id).where(
            or_(Patient.first_name.ilike(f"%{patient_name}%"),
                Patient.last_name.ilike(f"%{patient_name}%")))
    count = db.scalar(select(func.count()).select_from(q.subquery()))  # total (the client uses it to compute page count)
    orders = db.scalars(
        q.order_by(Order.id).offset((page - 1) * page_size).limit(page_size)  # fetch only this page: LIMIT/OFFSET
    ).all()
    return count, orders


def create_patient(db, first_name, last_name, mrn, dob=""):
    if db.scalar(select(Patient).where(Patient.mrn == mrn)):
        raise BlockError("This MRN already exists", code="DUPLICATE_MRN", detail={"mrn": mrn})
    dup = db.scalar(select(Patient).where(
        Patient.first_name == first_name, Patient.last_name == last_name, Patient.dob == dob))
    if dup:
        raise WarningException("A patient with the same name and DOB already exists; please verify",
                               code="PATIENT_POSSIBLE_DUPLICATE",
                               detail={"existing_patient_id": dup.id})
    p = Patient(first_name=first_name, last_name=last_name, mrn=mrn, dob=dob)
    db.add(p); db.commit(); db.refresh(p)
    return p


def list_patients(db, page, page_size, search=None):
    q = select(Patient)
    if search:
        q = q.where(or_(Patient.first_name.ilike(f"%{search}%"),
                        Patient.last_name.ilike(f"%{search}%")))
    count = db.scalar(select(func.count()).select_from(q.subquery()))
    patients = db.scalars(
        q.order_by(Patient.id).offset((page - 1) * page_size).limit(page_size)).all()
    return count, patients


def get_patient(db, patient_id):
    return db.get(Patient, patient_id)


def update_patient(db, patient_id, first_name=None, last_name=None, dob=None):
    p = db.get(Patient, patient_id)
    if p is None:
        return None
    if first_name is not None: p.first_name = first_name      # mrn isn't a parameter -> can't be changed
    if last_name is not None: p.last_name = last_name
    if dob is not None: p.dob = dob
    db.commit(); db.refresh(p)
    return p


def delete_patient(db, patient_id):
    p = db.get(Patient, patient_id)
    if p is None:
        return False
    orders = db.scalars(select(Order).where(Order.patient_id == patient_id)).all()
    if orders:  # don't allow deletion if there are order records (especially active pending/processing ones)
        active = [o.id for o in orders if (o.care_plan and o.care_plan.status in ("pending", "processing"))]
        raise BlockError("This patient has order records and cannot be deleted",
                         code="PATIENT_HAS_ORDERS",
                         detail={"order_ids": [o.id for o in orders], "active_orders": active})
    db.delete(p); db.commit()
    return True


def create_provider(db, name, npi):
    by_npi = db.scalar(select(Provider).where(Provider.npi == npi))
    if by_npi is not None:
        if by_npi.name == name:
            raise BlockError("This NPI is already registered", code="DUPLICATE_NPI",
                             detail={"existing_provider_id": by_npi.id})
        raise BlockError("This NPI already exists but under a different name; please verify", code="PROVIDER_NPI_CONFLICT",
                         detail={"existing_name": by_npi.name})
    by_name = db.scalar(select(Provider).where(Provider.name == name))
    if by_name is not None:  # same name, different NPI -> warning
        raise WarningException("A provider with the same name already exists (different NPI); please verify",
                               code="PROVIDER_NAME_DUP",
                               detail={"existing_provider_id": by_name.id, "existing_npi": by_name.npi})
    prov = Provider(name=name, npi=npi)
    db.add(prov); db.commit(); db.refresh(prov)
    return prov


def get_patient_orders(db, patient_id):
    return db.scalars(select(Order).where(Order.patient_id == patient_id).order_by(Order.id)).all()


def retry_order(db, order_id):
    order = db.get(Order, order_id)
    if order is None:
        return None
    cp = order.care_plan
    if cp is None or cp.status != "failed":  # only a failed order can be retried
        raise BlockError("Order is not in failed status and cannot be retried", code="NOT_FAILED",
                         detail={"current_status": cp.status if cp else "unknown"})
    cp.status = "pending"; db.commit()       # reset to pending; enqueueing is the caller's responsibility
    return order
