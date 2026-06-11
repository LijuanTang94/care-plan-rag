"""Adapter layer -- "translates" each source's messy format into an InternalOrder.

Each adapter does exactly one thing: format conversion. Validation, duplicate
detection, and LLM calls don't live here (the service layer does those once, in
one place). Adding a data source = add one adapter + register it in the factory.
"""

import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod

from careplan.exceptions import ValidationError
from careplan.internal_order import InternalOrder


class BaseIntakeAdapter(ABC):
    """Interface for all adapters: take raw bytes, return an InternalOrder."""

    @abstractmethod
    def transform(self, body: bytes) -> InternalOrder:
        ...


class CVSAdapter(BaseIntakeAdapter):
    """CVS's own format -- already our naming, so barely any translation needed."""

    def transform(self, body: bytes) -> InternalOrder:
        d = json.loads(body)
        return InternalOrder(
            patient_first_name=d["patient_first_name"],
            patient_last_name=d["patient_last_name"],
            patient_dob=d.get("patient_dob", ""),
            patient_mrn=d["patient_mrn"],
            referring_provider=d["referring_provider"],
            referring_provider_npi=d["referring_provider_npi"],
            primary_diagnosis=d["primary_diagnosis"],
            medication_name=d["medication_name"],
            patient_records=d.get("patient_records", ""),
            confirm=d.get("confirm", False),
        )


class ClinicBAdapter(BaseIntakeAdapter):
    """Small-clinic JSON: pt.fname / provider.npi_num / rx.med_name ..."""

    def transform(self, body: bytes) -> InternalOrder:
        d = json.loads(body)
        pt, prov, dx, rx = d["pt"], d["provider"], d["dx"], d["rx"]
        return InternalOrder(
            patient_first_name=pt["fname"],
            patient_last_name=pt["lname"],
            patient_dob=pt.get("dob", ""),
            patient_mrn=pt["mrn"],
            referring_provider=prov["name"],
            referring_provider_npi=prov["npi_num"],
            primary_diagnosis=dx["primary"],
            medication_name=rx["med_name"],
            patient_records=d.get("clinical_notes", ""),
        )


class PharmaCorpAdapter(BaseIntakeAdapter):
    """Pharma XML: <FirstName> / <NPINumber> / <DrugName> ..."""

    def transform(self, body: bytes) -> InternalOrder:
        root = ET.fromstring(body)
        name = root.find("PatientInformation/PatientName")
        return InternalOrder(
            patient_first_name=name.findtext("FirstName"),
            patient_last_name=name.findtext("LastName"),
            patient_dob=root.findtext("PatientInformation/DateOfBirth", ""),
            patient_mrn=root.findtext("PatientInformation/MedicalRecordNumber"),
            referring_provider=root.findtext("PrescriberInformation/FullName"),
            referring_provider_npi=root.findtext("PrescriberInformation/NPINumber"),
            primary_diagnosis=root.findtext("DiagnosisList/PrimaryDiagnosis/ICDCode"),
            medication_name=root.findtext("MedicationOrder/DrugName"),
            patient_records=root.findtext("ClinicalDocumentation/NarrativeText", ""),
        )


# Factory: to add a data source, change only this + add one adapter class;
# the business code stays untouched.
_ADAPTERS = {
    "cvs": CVSAdapter,
    "clinic_b": ClinicBAdapter,
    "pharmacorp": PharmaCorpAdapter,
}


def get_adapter(source: str) -> BaseIntakeAdapter:
    cls = _ADAPTERS.get(source)
    if cls is None:
        raise ValidationError(f"Unknown data source: {source}", code="UNKNOWN_SOURCE", detail={"source": source})
    return cls()
