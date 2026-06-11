"""Generation quality evaluation: claim-level NLI three-way classification — the right metric for an "augmentation-style RAG" product.

Why not naive faithfulness (supported / total):
  The care-plan generator is augmentation-style RAG — the retrieved guidelines are
  "supplementary material", while the model's own general clinical knowledge is the core
  value, not a hallucination to be eliminated. Naive faithfulness lumps "added a correct
  piece of general knowledge (good)" together with "invented a wrong dose (dangerous)" —
  both counted as unsupported. Conflating them is the wrong KPI for this product.

Instead, classify each claim against the retrieved material into three categories (NLI-style entailment/neutral/contradiction):
  SUPPORTED    directly backed by the retrieved material
  NEUTRAL      not in the material but not in conflict either (reasonable general knowledge the model added) — acceptable, no penalty
  CONTRADICTED conflicts with the retrieved material (reversed dose, missed contraindication, calling a contraindication safe) — dangerous

So we report two metrics, each owning one concern:
  contradiction_rate = contradicted / total   primary metric, a safety signal, lower is better (target ≈ 0)
  grounding_coverage = supported / total       secondary, acts as an "out-of-scope detector": near 0 = the knowledge base doesn't cover this
                                                → should trigger a refusal / low-confidence alert, not fabricate an unsupported plan

The eval set deliberately mixes in drugs the knowledge base "doesn't cover" (Warfarin/Atorvastatin): expected coverage ≈ 0 (out of scope),
but contradiction is also low (the retrieved docs are about other conditions, "irrelevant ≠ contradictory") — neatly demonstrating "out of scope ≠ contradiction".

One level higher is correctness (whether the specific dose is actually right), which needs an authoritative reference / pharmacist-annotated gold answer; LLM self-grading can't provide it — left as the next direction.

The judge is pluggable: mock → heuristic placeholder (free, only proves the pipeline runs); LLM_PROVIDER=claude → real judgment (a few cents).
Usage: docker compose exec -e LLM_PROVIDER=claude app python eval_generation.py
"""

import os
import re

from db import SessionLocal
from llm_service import get_llm_service
from rag import retrieve

# Eval set: the first 3 drugs are covered by the knowledge base; the last 2 are deliberately uncovered (adversarial samples, to validate "out-of-scope detection")
CASES = [
    {"patient": "A. B.", "mrn": "000123", "provider": "Dr. Smith", "npi": "1234567890",
     "diagnosis": "G70.00", "medication": "IVIG", "covered": True},
    {"patient": "C. D.", "mrn": "000456", "provider": "Dr. Lee", "npi": "9876543210",
     "diagnosis": "E11", "medication": "Metformin", "covered": True},
    {"patient": "E. F.", "mrn": "000789", "provider": "Dr. Wong", "npi": "5555555555",
     "diagnosis": "I10", "medication": "Lisinopril", "covered": True},
    # —— The knowledge base has no matching docs for the following, so no support is retrievable → coverage should be ≈ 0 (out of scope) ——
    {"patient": "G. H.", "mrn": "000321", "provider": "Dr. Patel", "npi": "1112223334",
     "diagnosis": "I48", "medication": "Warfarin", "covered": False},
    {"patient": "I. J.", "mrn": "000654", "provider": "Dr. Kim", "npi": "4445556667",
     "diagnosis": "E78.5", "medication": "Atorvastatin", "covered": False},
]


def _judge_text(prompt: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return next(b.text for b in resp.content if b.type == "text")


def extract_claims(plan: str) -> list[str]:
    """Break a care plan into atomic clinical claims (one per line). Ignore headings/formatting/boilerplate, keep only verifiable facts."""
    prompt = (
        "Break the following pharmacist care plan into a list of atomic, verifiable clinical "
        "claims (one fact per line: dosages, drug choices, monitoring, risks, premedication). "
        "Ignore headings, formatting, and non-factual filler. Output ONLY the claims, one per "
        "line, no numbering, no extra text.\n\n"
        f"Care plan:\n{plan}"
    )
    text_out = _judge_text(prompt, max_tokens=800)
    return [ln.strip(" -*\t") for ln in text_out.splitlines() if ln.strip(" -*\t")]


def classify_claims(context: str, claims: list[str]) -> list[str]:
    """Classify each claim against context as SUPPORTED / NEUTRAL / CONTRADICTED (three-way NLI).
    A trap learned the hard way: don't ask the judge to "reply with only a string of numbers"
    (it'll add reasoning instead, and a regex grabbing digits from '1.' or '2g/kg' falls apart).
    Work with the model's instinct: have it output '<number>. LABEL' per claim, and parse by
    number + keyword (check CONTRADICTED first, then NEUTRAL, then SUPPORTED)."""
    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))
    prompt = (
        "Classify each clinical claim against the reference material below into exactly one label:\n"
        "- SUPPORTED: the reference material directly backs the claim (a dose, drug, monitoring "
        "step, target, or risk that actually appears in it).\n"
        "- CONTRADICTED: the claim conflicts with the reference material (e.g. a different dose, a "
        "missed contraindication, or calling something safe that the material flags as a risk).\n"
        "- NEUTRAL: the claim is not in the material but does not conflict with it (reasonable "
        "general clinical knowledge the material simply doesn't cover).\n\n"
        f"Reference material:\n{context}\n\n"
        f"Claims:\n{numbered}\n\n"
        "For EVERY claim, output exactly one line: the claim number, a period, and the single word "
        "SUPPORTED, CONTRADICTED, or NEUTRAL. No other commentary.\n"
        "Example:\n1. SUPPORTED\n2. NEUTRAL\n3. CONTRADICTED"
    )
    text_out = _judge_text(prompt, max_tokens=2000)
    by_num: dict[int, str] = {}
    for line in text_out.splitlines():
        m = re.match(r"\s*(\d+)\s*[.):\-]", line)
        if not m:
            continue
        up = line.upper()
        if "CONTRADICTED" in up:
            by_num[int(m.group(1))] = "CONTRADICTED"
        elif "NEUTRAL" in up:
            by_num[int(m.group(1))] = "NEUTRAL"
        elif "SUPPORTED" in up:   # checked last: CONTRADICTED doesn't contain "SUPPORTED", so only pure supported remains here
            by_num[int(m.group(1))] = "SUPPORTED"
    # Anything not parsed defaults conservatively to NEUTRAL (neither support nor contradiction, so it pollutes neither metric)
    return [by_num.get(i + 1, "NEUTRAL") for i in range(len(claims))]


def evaluate_case(context: str, plan: str) -> dict:
    """Returns {total, supported, neutral, contradicted, coverage, contradiction_rate}.
    Under mock it degrades to a heuristic placeholder (only a coverage proxy; contradiction can't be judged heuristically)."""
    if os.environ.get("LLM_PROVIDER") == "claude":
        claims = extract_claims(plan)
        if not claims:
            return {"total": 0, "supported": 0, "neutral": 0, "contradicted": 0,
                    "coverage": 0.0, "contradiction_rate": 0.0}
        labels = classify_claims(context, claims)
        n = len(labels)
        sup = labels.count("SUPPORTED")
        con = labels.count("CONTRADICTED")
        return {"total": n, "supported": sup, "neutral": labels.count("NEUTRAL"),
                "contradicted": con, "coverage": sup / n, "contradiction_rate": con / n}
    # Heuristic placeholder (free, zero variance): fraction of the plan's content words that appear in context, used only as a coverage proxy
    words = lambda s: set(re.findall(r"[a-zA-Z]{4,}", s.lower()))
    pw = words(plan)
    cov = len(pw & words(context)) / len(pw) if pw else 0.0
    return {"total": 0, "supported": 0, "neutral": 0, "contradicted": 0,
            "coverage": cov, "contradiction_rate": 0.0}


def main():
    real = os.environ.get("LLM_PROVIDER") == "claude"
    db = SessionLocal()
    try:
        results = []
        for c in CASES:
            refs = retrieve(db, f"{c['medication']} {c['diagnosis']}", k=3)
            context = "\n\n".join(f"[{r['source']}] {r['content']}" for r in refs)
            plan = get_llm_service().generate(
                patient_name=c["patient"], mrn=c["mrn"], provider_name=c["provider"],
                npi=c["npi"], diagnosis=c["diagnosis"], medication=c["medication"],
                records="", context=context,
            )
            r = evaluate_case(context, plan)
            results.append(r)
            tag = "covered" if c["covered"] else "uncovered (adversarial)"
            if real:
                print(f"  {c['medication']}/{c['diagnosis']} [{tag}]: "
                      f"contradiction={r['contradiction_rate']:.2f}  coverage={r['coverage']:.2f}  "
                      f"(supported {r['supported']}/neutral {r['neutral']}/contradicted {r['contradicted']} of {r['total']})")
            else:
                print(f"  {c['medication']}/{c['diagnosis']} [{tag}]: coverage≈{r['coverage']:.2f} (heuristic placeholder)")

        def avg(rs, key):
            return sum(x[key] for x in rs) / len(rs) if rs else 0.0

        cov_g = [r for r, c in zip(results, CASES) if c["covered"]]
        unc_g = [r for r, c in zip(results, CASES) if not c["covered"]]
        tag = "Claude three-way NLI judge, real scores" if real else "heuristic placeholder (use LLM_PROVIDER=claude for real scores)"
        print(f"\n[{tag}]")
        print(f"contradiction rate (primary metric, lower is better, target ≈ 0): overall {avg(results, 'contradiction_rate'):.2f}")
        print(f"grounding coverage (out-of-scope detector): covered group {avg(cov_g, 'coverage'):.2f}  vs  adversarial group {avg(unc_g, 'coverage'):.2f}")
        if real:
            print(f"  → covered group contradiction {avg(cov_g, 'contradiction_rate'):.2f} / adversarial group {avg(unc_g, 'contradiction_rate'):.2f}"
                  f"  (adversarial group coverage should be ≈ 0 but contradiction is also low → 'out of scope ≠ contradiction')")
    finally:
        db.close()


if __name__ == "__main__":
    main()
