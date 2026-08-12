"""Seed a sample clinical knowledge base (chunk + embed + store). Safe to re-run.
Usage: docker compose exec app python -m eval.seed_knowledge

Coverage of the knowledge base (deliberately designed): IVIG / myasthenia gravis,
metformin + insulin glargine / type 2 diabetes, hypertension (lisinopril, amlodipine,
hydrochlorothiazide), levothyroxine / hypothyroidism, ferrous sulfate / iron-deficiency
anemia, alendronate / osteoporosis, allopurinol / gout, care-plan structure, general
monitoring and patient education. It **deliberately excludes** anticoagulants (Warfarin,
Apixaban), statins (Atorvastatin), SSRIs (Sertraline), inhaled beta-agonists (Albuterol),
PPIs (Omeprazole) and gabapentinoids — these serve as adversarial samples in
eval_generation.py (no retrievable support → grounding coverage should drop to zero),
proving the evaluation metrics actually discriminate rather than emitting a constant score.
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

    "Insulin glargine in type 2 diabetes": (
        "Basal insulin such as insulin glargine is added when oral agents and lifestyle no longer "
        "reach the A1c goal. A common starting dose is 10 units once daily, or 0.1 to 0.2 units per "
        "kg per day, given at the same time each day. Titrate the dose by 2 to 4 units every 3 days "
        "based on the fasting morning glucose until the fasting target is met. The main risk is "
        "hypoglycemia; counsel the patient to recognize and treat it, rotate injection sites, and "
        "check fasting blood glucose regularly. Do not mix glargine with other insulins in the same syringe."
    ),

    # ---- hypertension ----
    "Amlodipine monograph": (
        "Amlodipine is a dihydropyridine calcium channel blocker used first-line for hypertension. "
        "Start at 5 mg once daily and titrate to a maximum of 10 mg once daily based on blood "
        "pressure response. Common side effects are dose-dependent peripheral (ankle) edema, "
        "flushing, and headache; the edema is not from fluid overload and does not respond well to "
        "diuretics. No routine laboratory monitoring is required. Recheck blood pressure 2 to 4 weeks "
        "after starting or changing the dose."
    ),
    "Hydrochlorothiazide monograph": (
        "Hydrochlorothiazide is a thiazide diuretic used first-line for hypertension, typically "
        "started at 12.5 to 25 mg once daily in the morning. Monitor serum electrolytes because it "
        "can cause hypokalemia and hyponatremia, and it may raise serum uric acid (precipitating "
        "gout) and blood glucose. Check a basic metabolic panel within 2 to 4 weeks of initiation. "
        "Counsel the patient on dizziness from volume depletion and to report muscle cramps or weakness."
    ),

    # ---- levothyroxine / hypothyroidism ----
    "Levothyroxine monograph": (
        "Levothyroxine is synthetic T4 and is first-line replacement for primary hypothyroidism "
        "(ICD-10 E03.9). The usual full replacement dose is about 1.6 mcg per kg per day, but start "
        "low at 25 to 50 mcg daily in older adults or those with coronary artery disease to avoid "
        "precipitating arrhythmia or angina. Take it once daily on an empty stomach, 30 to 60 minutes "
        "before breakfast, and separate it from calcium, iron, and antacids by at least 4 hours. "
        "Over-replacement risks atrial fibrillation and reduced bone density."
    ),
    "Levothyroxine monitoring plan": (
        "After starting levothyroxine or changing the dose, recheck serum TSH in 6 to 8 weeks because "
        "the full effect takes weeks to stabilize; adjust the dose in small increments to bring TSH "
        "into the target range. Once stable, monitor TSH every 6 to 12 months. Symptoms of "
        "under-treatment include fatigue, cold intolerance, and constipation; over-treatment causes "
        "palpitations, tremor, heat intolerance, and weight loss. Counsel on consistent daily timing "
        "and separation from interfering foods and supplements."
    ),

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

    # ---- iron-deficiency anemia ----
    "Ferrous sulfate monograph": (
        "Ferrous sulfate is first-line oral iron replacement for iron-deficiency anemia (ICD-10 "
        "D50.9). A common regimen provides about 65 mg of elemental iron once daily or every other "
        "day; alternate-day dosing can improve fractional absorption and gastrointestinal "
        "tolerability. Take on an empty stomach for best absorption, or with food if it causes upset; "
        "vitamin C enhances absorption. Common side effects are constipation, nausea, and dark "
        "stools. Separate iron from calcium, antacids, and levothyroxine by several hours."
    ),
    "Iron-deficiency anemia monitoring": (
        "After starting oral iron, expect a reticulocyte rise within about 1 week and a hemoglobin "
        "increase of roughly 1 g/dL every 2 to 4 weeks. Recheck hemoglobin and ferritin at about 4 "
        "and 8 to 12 weeks to confirm response. Continue iron for about 3 months after the anemia "
        "resolves to replenish body stores. Investigate the underlying cause of iron deficiency, and "
        "counsel the patient that dark stools are expected and not alarming."
    ),

    # ---- osteoporosis ----
    "Alendronate monograph": (
        "Alendronate is an oral bisphosphonate used first-line for osteoporosis (ICD-10 M81.0), "
        "dosed 70 mg once weekly or 10 mg once daily. Take it first thing in the morning with a full "
        "glass of plain water, at least 30 minutes before any food, drink, or other medication, and "
        "remain upright (sitting or standing) for at least 30 minutes to reduce the risk of "
        "esophageal irritation. Ensure adequate calcium and vitamin D intake. It is contraindicated "
        "in esophageal disorders and in patients unable to stay upright. Counsel on the rare "
        "long-term risks of osteonecrosis of the jaw and atypical femoral fracture, and reassess the "
        "need for continued therapy after 3 to 5 years."
    ),

    # ---- gout ----
    "Allopurinol monograph": (
        "Allopurinol is a xanthine oxidase inhibitor used for chronic gout to lower serum urate; it "
        "is a maintenance agent and is not used to treat an acute flare. Start low at 100 mg daily "
        "(50 mg with renal impairment) and titrate every 2 to 5 weeks toward a serum urate target "
        "below 6 mg/dL. Because starting or increasing urate-lowering therapy can itself precipitate "
        "an acute flare, co-prescribe flare prophylaxis (low-dose colchicine or an NSAID) during "
        "initiation. Counsel the patient to stop the drug and seek care immediately if a rash "
        "develops, as rare but serious allopurinol hypersensitivity syndrome can occur. Monitor "
        "serum urate, renal function, and liver enzymes."
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
