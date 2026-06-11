"""Seed a sample clinical knowledge base (chunk + embed + store). Safe to re-run.
Usage: docker compose exec app python -m eval.seed_knowledge

Coverage of the knowledge base (deliberately designed): IVIG / myasthenia gravis,
metformin / type 2 diabetes, hypertension, care-plan structure, general monitoring and
patient education. It **deliberately excludes** Warfarin / Atorvastatin — these serve as
adversarial samples in eval_generation.py (no retrievable support → faithfulness should
drop to zero), proving the evaluation metrics actually discriminate rather than emitting a
constant score.
"""

from sqlalchemy import text

from careplan.db import SessionLocal
from careplan.rag import ingest

DOCS = {
    # ---- IVIG / myasthenia gravis ----
    "IVIG monograph": (
        "Intravenous immunoglobulin (IVIG) for generalized myasthenia gravis is typically "
        "dosed at 2 g/kg divided over 2 to 5 days. Common infusion-related reactions include "
        "headache, fever, chills and flushing; slow the infusion rate to manage them. Key risks "
        "are acute kidney injury, thromboembolism and aseptic meningitis. Confirm baseline IgA "
        "(IgA-deficient patients risk anaphylaxis). Premedicate with acetaminophen and "
        "diphenhydramine. Monitor renal function (BMP) before and after the course and ensure hydration."
    ),
    "IVIG infusion protocol": (
        "Start the IVIG infusion at a slow rate and titrate up as tolerated; most reactions occur "
        "early. Ensure the patient is well hydrated before and during the infusion to reduce renal "
        "and thrombotic risk. Premedicate 30 to 60 minutes prior with acetaminophen 650 mg and "
        "diphenhydramine 25 to 50 mg. If a reaction occurs, stop or slow the infusion, treat "
        "symptoms, and resume at a lower rate once stable. Record vital signs before, during, and "
        "after the infusion. Do not exceed the maximum recommended infusion rate for the product."
    ),
    "IVIG monitoring plan": (
        "Before IVIG, obtain baseline renal function (serum creatinine and BUN), a complete blood "
        "count, and serum IgA level. During and after the course, monitor renal function for acute "
        "kidney injury and watch for signs of thromboembolism such as chest pain, dyspnea, or limb "
        "swelling. Counsel the patient to report severe headache or neck stiffness, which may "
        "indicate aseptic meningitis. Re-check a basic metabolic panel after the course completes."
    ),
    "Myasthenia gravis guideline": (
        "Generalized myasthenia gravis (ICD-10 G70.00) is an autoimmune disorder of the "
        "neuromuscular junction. For acute exacerbation, IVIG or plasmapheresis provides rapid "
        "symptom control. Pyridostigmine is used symptomatically; corticosteroids and "
        "steroid-sparing agents for maintenance. Track response with the MG-ADL score. Avoid drugs "
        "known to worsen myasthenia where possible, and educate the patient on recognizing a "
        "myasthenic crisis (worsening weakness, trouble breathing or swallowing) and when to seek care."
    ),

    # ---- metformin / type 2 diabetes ----
    "Metformin monograph": (
        "Metformin is first-line for type 2 diabetes. Start at 500 mg once or twice daily and "
        "titrate to limit gastrointestinal side effects such as nausea and diarrhea. It is "
        "contraindicated in significant renal impairment due to lactic acidosis risk. Monitor "
        "renal function and vitamin B12 periodically."
    ),
    "Metformin dosing and titration": (
        "Initiate metformin at 500 mg once daily with the evening meal, or 500 mg twice daily, to "
        "improve gastrointestinal tolerability. Increase the dose gradually every 1 to 2 weeks as "
        "tolerated. The usual effective dose is 1000 mg twice daily, and the maximum is 2000 to "
        "2550 mg per day. Taking metformin with food reduces nausea and diarrhea. Use extended-release "
        "metformin if immediate-release is not tolerated."
    ),
    "Metformin monitoring and safety": (
        "Assess renal function (eGFR) before starting metformin and at least annually. Do not start "
        "metformin if eGFR is below 30 mL/min/1.73m2, and do not initiate between 30 and 45. Hold "
        "metformin around iodinated contrast procedures and during acute illness with dehydration. "
        "Monitor vitamin B12 periodically because long-term use can cause deficiency. Counsel the "
        "patient on symptoms of lactic acidosis: malaise, muscle pain, trouble breathing, and unusual "
        "drowsiness, and to seek care if they occur."
    ),
    "Type 2 diabetes management": (
        "Type 2 diabetes (ICD-10 E11) management combines lifestyle changes with pharmacotherapy. "
        "Metformin is the preferred first-line agent. A common glycemic target is an A1c below 7 "
        "percent, individualized to the patient. Reinforce diet, physical activity, weight management, "
        "and self-monitoring of blood glucose. Add a second agent such as a GLP-1 receptor agonist or "
        "SGLT2 inhibitor if A1c remains above goal, especially with cardiovascular or kidney disease."
    ),

    # ---- hypertension ----
    "Hypertension guideline": (
        "Essential hypertension (ICD-10 I10) management combines lifestyle change with "
        "pharmacotherapy: ACE inhibitors, ARBs, calcium channel blockers, or thiazide diuretics. "
        "A common target is below 130/80 mmHg. Monitor blood pressure, electrolytes and renal function."
    ),
    "Antihypertensive drug classes": (
        "First-line antihypertensive classes are ACE inhibitors (such as lisinopril), angiotensin "
        "receptor blockers, dihydropyridine calcium channel blockers, and thiazide diuretics. ACE "
        "inhibitors can cause cough and, rarely, angioedema, and require monitoring of potassium and "
        "renal function. Lisinopril is usually started at 10 mg once daily and titrated by blood "
        "pressure response. Avoid combining an ACE inhibitor with an ARB."
    ),
    "Hypertension monitoring plan": (
        "After starting or changing an antihypertensive, recheck blood pressure within 2 to 4 weeks "
        "and titrate to a target below 130/80 mmHg for most patients. For ACE inhibitors or ARBs, "
        "check serum potassium and renal function within 1 to 2 weeks of initiation or dose change. "
        "Encourage home blood pressure monitoring and counsel on lifestyle: reduced sodium intake, "
        "the DASH diet, regular physical activity, weight loss, and limiting alcohol."
    ),

    # ---- care-plan structure / general ----
    "Care plan template": (
        "A pharmacist care plan must contain four sections. 1) Problem list / drug therapy "
        "problems. 2) Goals written in SMART form. 3) Pharmacist interventions and plan including "
        "dosing, administration, premedication and monitoring. 4) Monitoring plan and lab schedule "
        "with baseline, during-therapy and post-therapy checks."
    ),
    "SMART goals in care plans": (
        "Goals in a pharmacist care plan should be SMART: specific, measurable, achievable, relevant, "
        "and time-bound. Examples include reaching a target blood pressure below 130/80 mmHg within "
        "three months, or lowering A1c below 7 percent within six months. Each goal should tie to a "
        "monitoring parameter and a follow-up timeframe so progress can be tracked objectively."
    ),
    "Medication counseling and adherence": (
        "Counsel every patient on the indication, dose, administration, common side effects, and what "
        "to do if a dose is missed. Assess and support adherence, and document patient education. "
        "Provide a clear follow-up plan stating when the patient will be reassessed and which "
        "parameters will be checked. Advise the patient on warning signs that should prompt them to "
        "contact a clinician promptly."
    ),
}


def main():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM knowledge_chunks"))  # safe to re-run
        db.commit()
        total = sum(ingest(db, src, content) for src, content in DOCS.items())
        print(f"seeded {total} chunks from {len(DOCS)} docs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
