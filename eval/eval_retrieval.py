"""Retrieval quality evaluation: recall@k / precision@k / MRR / hit@k — quantifying "how accurately we retrieve".
This is the dividing line between "real RAG vs toy RAG". Falling below the threshold exits with code 1 (usable as a CI gate).

Usage: docker compose exec app python -m eval.eval_retrieval
(Use real embeddings: EMBED_PROVIDER=fastembed; mock has no semantics, so the numbers will be poor.)
"""

import sys

from careplan.db import SessionLocal
from careplan.rag import retrieve

K = 3
RECALL_GATE = 0.80  # below this counts as a regression, exit code 1

# (query, set of expected relevant sources). Includes paraphrased phrasings to test semantic retrieval (not keywords).
DATASET = [
    ("IVIG dosing 2 g/kg over several days", {"IVIG monograph"}),
    ("how to manage infusion reactions and premedication for IVIG", {"IVIG monograph"}),
    ("acute exacerbation of myasthenia gravis treatment", {"Myasthenia gravis guideline", "IVIG monograph"}),
    ("how is MG severity tracked", {"Myasthenia gravis guideline"}),
    ("starting dose of metformin", {"Metformin monograph"}),
    ("metformin and kidney function lactic acidosis risk", {"Metformin monograph"}),
    ("first line drug for type 2 diabetes", {"Metformin monograph"}),
    ("target blood pressure for hypertension", {"Hypertension guideline"}),
    ("ACE inhibitor or thiazide for high blood pressure", {"Hypertension guideline"}),
    ("what sections belong in a pharmacist care plan", {"Care plan template"}),
    ("SMART goals in a care plan", {"Care plan template"}),
]


def main():
    db = SessionLocal()
    try:
        n = len(DATASET)
        sum_recall = sum_prec = sum_mrr = sum_hit = 0.0
        for query, relevant in DATASET:
            got = [r["source"] for r in retrieve(db, query, k=K)]
            inter = [s for s in got if s in relevant]
            recall = len(set(got) & relevant) / len(relevant)
            precision = len(inter) / K
            rr = next((1 / (i + 1) for i, s in enumerate(got) if s in relevant), 0.0)
            hit = 1.0 if inter else 0.0
            sum_recall += recall; sum_prec += precision; sum_mrr += rr; sum_hit += hit
            print(f"{'✅' if hit else '❌'} recall={recall:.2f} rr={rr:.2f} | '{query}' → {got}")

        print(f"\n— eval set: {n} queries, k={K} —")
        print(f"recall@{K}   = {sum_recall / n:.2f}   (did the documents that should hit make it into top-k)")
        print(f"precision@{K}= {sum_prec / n:.2f}   (note: relevant docs are often < k, so the ceiling is low; use it to gauge noise)")
        print(f"MRR        = {sum_mrr / n:.2f}   (how high the correct doc is ranked)")
        print(f"hit@{K}     = {sum_hit / n:.2f}   (fraction with at least one hit)")

        if sum_recall / n < RECALL_GATE:
            print(f"\nFAIL: recall@{K} below the gate of {RECALL_GATE}, exit code 1")
            sys.exit(1)
        print(f"\nPASS (recall@{K} ≥ {RECALL_GATE})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
