"""Adapter tests: every source's format translates correctly into an InternalOrder."""

import json

import pytest

from adapters import ClinicBAdapter, PharmaCorpAdapter, get_adapter
from exceptions import ValidationError

CLINIC_JSON = {
    "pt": {"mrn": "234567", "fname": "Jane", "lname": "Smith", "dob": "03/22/1985"},
    "provider": {"name": "Dr. Emily Johnson", "npi_num": "0987654321"},
    "dx": {"primary": "G70.00"},
    "rx": {"med_name": "Gamunex-C"},
    "clinical_notes": "progressive weakness, IVIG recommended",
}

PHARMA_XML = b"""<?xml version="1.0"?>
<CareOrderRequest>
  <PatientInformation>
    <MedicalRecordNumber>345678</MedicalRecordNumber>
    <PatientName><FirstName>Robert</FirstName><LastName>Williams</LastName></PatientName>
    <DateOfBirth>1972-11-30</DateOfBirth>
  </PatientInformation>
  <PrescriberInformation><FullName>Dr. Michael Chen</FullName><NPINumber>5678901234</NPINumber></PrescriberInformation>
  <DiagnosisList><PrimaryDiagnosis><ICDCode>G70.01</ICDCode></PrimaryDiagnosis></DiagnosisList>
  <MedicationOrder><DrugName>Octagam</DrugName></MedicationOrder>
  <ClinicalDocumentation><NarrativeText>acute exacerbation, IVIG 2g/kg</NarrativeText></ClinicalDocumentation>
</CareOrderRequest>"""


def test_clinic_adapter_maps_fields():
    io = ClinicBAdapter().transform(json.dumps(CLINIC_JSON).encode())
    assert io.patient_first_name == "Jane"
    assert io.patient_mrn == "234567"
    assert io.referring_provider_npi == "0987654321"
    assert io.medication_name == "Gamunex-C"


def test_pharma_adapter_maps_fields():
    io = PharmaCorpAdapter().transform(PHARMA_XML)
    assert io.patient_first_name == "Robert"
    assert io.patient_mrn == "345678"
    assert io.referring_provider_npi == "5678901234"
    assert io.medication_name == "Octagam"


def test_unknown_source_raises():
    with pytest.raises(ValidationError):
        get_adapter("nope")


def test_intake_clinic_endpoint(client):
    r = client.post("/api/v1/intake/clinic_b", content=json.dumps(CLINIC_JSON))
    assert r.status_code == 200
    assert "careplan_id" in r.json()


def test_intake_pharma_endpoint(client):
    r = client.post("/api/v1/intake/pharmacorp", content=PHARMA_XML)
    assert r.status_code == 200
    assert "careplan_id" in r.json()
