"""The internal canonical format.

Every data source (CVS web form / clinic JSON / pharma XML) is first translated
into this format. The service layer only ever sees this -- we decide what the
fields are called, independent of however upstream names them.
"""

from dataclasses import dataclass


@dataclass
class InternalOrder:
    patient_first_name: str
    patient_last_name: str
    patient_dob: str
    patient_mrn: str
    referring_provider: str
    referring_provider_npi: str
    primary_diagnosis: str
    medication_name: str
    patient_records: str = ""
    confirm: bool = False
