# Care Plan Generator — Design Doc

> Status: **Draft** · Owner: LijuanTang94 · Last updated: 2026-06-09
>
> Note: This is the initial design document; its purpose is to lock down the results of requirements clarification. Specific technical details will be revised as the project evolves.

---

## 1. Background & Goals

**Customer:** A specialty pharmacy (modeled on CVS as a reference).

**Problem:** Pharmacists currently write a care plan for each patient by hand, taking 20–40 minutes per plan. This is a compliance requirement for Medicare and pharma reimbursement, but understaffing has led to a serious backlog.

**Goal:** Let pharmacists enter a patient's clinical information into a web form, have the system call an LLM to automatically generate a downloadable care plan, and support exporting reports.

**Success Metrics:**
- Reduce the time to generate a single care plan from 20–40 minutes to a matter of minutes
- 100% of entered data is validated, reducing dirty data
- Duplicate orders / duplicate patients / duplicate providers are detected and flagged

---

## 2. Users & Use Cases

| Role | Description |
| --- | --- |
| **Pharmacist** | The only direct user. Enters patient information at the counter, generates the care plan, and prints it for the patient |
| Patient | **Does not interact with the system.** Only receives the printed care plan |
| Pharma / Medicare | Consumes data indirectly through exported reports, for reimbursement and compliance; not a system user |

**Core flow:** The pharmacist enters the order information → the system validates + detects duplicates → calls the LLM to generate the care plan → the pharmacist downloads/prints it.

---

## 3. Scope

### 3.1 Input Fields
| Field | Type | Validation |
| --- | --- | --- |
| Patient First Name | string | Required |
| Patient Last Name | string | Required |
| Referring Provider | string | Required |
| Referring Provider NPI | 10 digits | Required, unique identifier |
| Patient MRN | 6-digit unique number | Required, unique |
| Primary Diagnosis | ICD-10 code | Required |
| Medication Name | string | Required |
| Additional Diagnosis | list of ICD-10 | Optional |
| Medication History | list of string | Optional |
| Patient Records | string or PDF | Optional |

### 3.2 Care Plan Definition
- **One care plan corresponds to one order (one medication)**
- The output must include: **Problem list, Goals, Pharmacist interventions, Monitoring plan**
- Provided as a downloadable text file

### 3.3 Functional Requirements (Must-have)
| Feature | Description |
| --- | --- |
| Patient/order duplicate detection | Must not disrupt the existing workflow |
| Care Plan generation (LLM) | Core value |
| Provider duplicate detection | Affects the pharma report |
| Export reports | Needed for the pharma report |
| Care Plan download | Users need to upload it into their own system |

### 3.4 Out of Scope (deferred, to prevent scope creep)
- Any patient-facing interface
- Batch processing / automatic refills
- Real-time integration with external EHR systems

---

## 4. Duplicate Detection Rules

> Core principle: **If it's definitely an error → ERROR (block); if it might be a legitimate action → WARNING (flag, can continue after confirmation).**

| Scenario | Handling | Reason |
| --- | --- | --- |
| Same patient + same medication + same day | ❌ **ERROR** | Almost certainly a duplicate submission |
| Same patient + same medication + different day | ⚠️ **WARNING** | Could be a refill |
| Same MRN + different name or DOB | ⚠️ **WARNING** | Could be a data-entry error |
| Same name + same DOB + different MRN | ⚠️ **WARNING** | Could be the same person |
| Same NPI + different provider name | ❌ **ERROR** | NPI is the unique identifier and must be corrected |

WARNING behavior: flag the user, but allow them to confirm and continue submitting.
ERROR behavior: block submission and require correction.

---

## 5. Production-Ready Requirements
- Every input is validated
- Integrity rules consistently enforce consistency
- Error handling is safe, clear, and controlled
- Code is modular and easy to navigate
- Critical logic is covered by automated tests
- The project runs end-to-end out of the box

---

## 6. Tech Stack (Tentative — decided on later days)
- Backend: Python / **FastAPI** + Docker
- Data validation: Pydantic (built into FastAPI, a perfect fit for field validation)
- Async tasks: message queue + Celery
- Database: relational + SQLAlchemy
- LLM: call an external LLM API to generate the care plan
- Deployment: AWS + Terraform

> At this stage we don't lock down implementation details; the priority is keeping the requirements and boundaries clear.

---

## 7. Open Questions & Assumptions
- Which vendor provides the LLM? Are there compliance/privacy (PHI/HIPAA) constraints? → **Assume yes; de-identification will need to be handled later**
- Is there a fixed template for the care plan text format? → Tentatively includes the four main blocks (see 3.2)
- What format for report export (CSV / PDF)? → TBD
