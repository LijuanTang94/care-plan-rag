"""Schema layer (called serializers in Django).

Does just two things:
1. Validate + accept data sent by the client (request models, e.g. OrderIn)
2. Shape database objects into the "format returned to the client"
   (response models + from_order)

No business logic (no LLM calls, no database access). Rule of thumb: swap the
frontend framework and this layer wouldn't need to change.
"""

from pydantic import BaseModel

from careplan.exceptions import ValidationError
from careplan.internal_order import InternalOrder


class OrderIn(BaseModel):
    """Patient information posted in (request model + basic validation)."""

    patient_first_name: str
    patient_last_name: str
    referring_provider: str
    referring_provider_npi: str
    patient_mrn: str
    patient_dob: str = ""          # date of birth, used for patient duplicate detection
    primary_diagnosis: str
    medication_name: str
    patient_records: str = ""
    confirm: bool = False          # after acknowledging a warning, resubmit with confirm=true to skip it


def validate_order_input(order_in: InternalOrder) -> None:
    """Format validation (schema layer: things decidable from the input alone).
    Raise ValidationError (400) if invalid.

    Note: (1) the input has already been translated into an InternalOrder by an
    adapter, so this is written once regardless of which data source it came from.
    (2) This is not the same as "duplicate detection" -- that hits the database
    and belongs to the service layer.
    """
    npi = order_in.referring_provider_npi
    if not (npi.isdigit() and len(npi) == 10):
        raise ValidationError(
            "NPI must be a 10-digit number", code="INVALID_NPI", detail={"npi": npi}
        )

    mrn = order_in.patient_mrn
    if not (mrn.isdigit() and len(mrn) == 6):
        raise ValidationError(
            "MRN must be a 6-digit number", code="INVALID_MRN", detail={"mrn": mrn}
        )


class OrderAck(BaseModel):
    """Response to the POST: received."""

    id: int
    careplan_id: int
    patient_name: str
    medication_name: str
    status: str
    message: str

    @classmethod
    def from_order(cls, order, message: str = "Received; generating in the background") -> "OrderAck":
        return cls(
            id=order.id,
            careplan_id=order.care_plan.id,
            patient_name=f"{order.patient.first_name} {order.patient.last_name}",
            medication_name=order.medication_name,
            status=order.care_plan.status,
            message=message,
        )


class OrderDetail(BaseModel):
    """Response for GET order detail."""

    id: int
    patient_name: str
    medication_name: str
    status: str
    care_plan: str

    @classmethod
    def from_order(cls, order) -> "OrderDetail":
        cp = order.care_plan
        return cls(
            id=order.id,
            patient_name=f"{order.patient.first_name} {order.patient.last_name}",
            medication_name=order.medication_name,
            status=cp.status if cp else "pending",
            care_plan=cp.content if cp else "",
        )


class OrderStatus(BaseModel):
    """Response for the lightweight status query (used by client polling)."""

    id: int
    status: str
    care_plan: str

    @classmethod
    def from_order(cls, order) -> "OrderStatus":
        cp = order.care_plan
        status = cp.status if cp else "pending"
        return cls(
            id=order.id,
            status=status,
            care_plan=cp.content if (cp and status == "completed") else "",
        )


# ===== Patient / Provider CRUD input + validation =====

class PatientIn(BaseModel):
    first_name: str
    last_name: str
    mrn: str
    dob: str = ""


class PatientUpdate(BaseModel):
    # Note: no mrn here -- MRN is not allowed to be changed
    first_name: str | None = None
    last_name: str | None = None
    dob: str | None = None


class ProviderIn(BaseModel):
    name: str
    npi: str


def validate_patient(p: PatientIn) -> None:
    if not p.first_name.strip() or not p.last_name.strip():
        raise ValidationError("Name cannot be empty", code="INVALID_NAME")
    if not (p.mrn.isdigit() and len(p.mrn) == 6):
        raise ValidationError("MRN must be a 6-digit number", code="INVALID_MRN", detail={"mrn": p.mrn})


def validate_provider(p: ProviderIn) -> None:
    if not p.name.strip():
        raise ValidationError("Name cannot be empty", code="INVALID_NAME")
    if not (p.npi.isdigit() and len(p.npi) == 10):
        raise ValidationError("NPI must be a 10-digit number", code="INVALID_NPI", detail={"npi": p.npi})
