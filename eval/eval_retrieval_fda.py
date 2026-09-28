"""Retrieval ablation on the FDA label corpus: BM25-only vs kNN-only vs hybrid (RRF).

Ground truth comes from the corpus structure, not hand labels: a query built from drug D and
label section S is answered by the document "FDA label: D — S". Three query sets:

  generic     "Who should not take lamotrigine?"        -> lamotrigine — Contraindications
  brand       "Who should not take Lamictal?"           -> same target; label text rarely says the brand
  look-alike  queries for ISMP confused-name pairs (tramadol / trazodone, ...); also reports how
              often the partner drug is ranked first — the dangerous failure in a clinical setting

Metrics (k=3, the production setting): drug@3 = a top-3 chunk is from the right drug's label;
section@3 = a top-3 chunk is from the exact right section. MRR@10 is over the exact section.

    docker compose exec app python -m eval.load_fda_corpus      # once
    docker compose exec app python -m eval.eval_retrieval_fda
"""

import difflib
import gzip
import json
import random
import re
import sys
from pathlib import Path

from careplan import es_search
from careplan.embedding_service import get_embedder
from eval.load_fda_corpus import CORPUS, PREFIX, source_name

SEED = 7
N_GENERIC = 150
N_BRAND = 60
K = 3

QUESTIONS = {
    "Boxed warning": "Does {d} have a boxed warning?",
    "Indications and usage": "What is {d} used to treat?",
    "Dosage and administration": "What is the recommended starting dose of {d}?",
    "Contraindications": "Who should not take {d}?",
    "Warnings and precautions": "What are the serious warnings and precautions for {d}?",
    "Adverse reactions": "What are the most common side effects of {d}?",
    "Drug interactions": "Which medications interact with {d}?",
    "Use in specific populations": "Is {d} safe during pregnancy or breastfeeding?",
}

# ISMP list of confused drug names; only pairs with both drugs in the corpus are used.
LOOK_ALIKE = [("tramadol", "trazodone"), ("lamotrigine", "lamivudine"), ("risperidone", "ropinirole"),
              ("sitagliptin", "sumatriptan"), ("celecoxib", "citalopram"), ("losartan", "valsartan"),
              ("fluoxetine", "paroxetine"), ("hydromorphone", "morphine"), ("topiramate", "torsemide"),
              ("olanzapine", "quetiapine"), ("glimepiride", "glipizide"), ("hydroxyzine", "hydralazine"),
              ("clonidine", "clonazepam"), ("bupropion", "buspirone"), ("prednisone", "prednisolone")]
LOOK_ALIKE_SECTIONS = ["Contraindications", "Dosage and administration"]

# Descriptors that show up in brand_name for store-brand OTC products; not real brand names.
NOT_A_BRAND = re.compile(r"\d|\b(acid|reducer|relief|control|allergy|pain|sleep|mg|care|health|"
                         r"equate|kirkland|up|good|signature|rite|basic|leader)\b", re.I)


def load_drugs() -> list[dict]:
    with gzip.open(CORPUS, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def clean_brand(d: dict) -> str | None:
    """First word of the first real brand name ("TOPROL XL" -> "Toprol"), skipping misspelled generics."""
    generic = d["drug"].split()[0]
    for b in d["brand_names"]:
        word = b.split()[0]
        if len(word) < 4 or NOT_A_BRAND.search(b):
            continue
        if difflib.SequenceMatcher(None, word.lower(), generic).ratio() > 0.6:
            continue
        return word.title() if word.isupper() else word
    return None


def build_queries(drugs: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    pairs = [(d, s) for d in drugs for s in d["sections"] if s in QUESTIONS]
    generic = [{"set": "generic", "q": QUESTIONS[s].format(d=d["drug"]), "drug": d["drug"], "section": s}
               for d, s in rng.sample(pairs, N_GENERIC)]

    branded = [(d, s, clean_brand(d)) for d, s in pairs if clean_brand(d)]
    brand = [{"set": "brand", "q": QUESTIONS[s].format(d=b), "drug": d["drug"], "section": s, "brand": b}
             for d, s, b in rng.sample(branded, min(N_BRAND, len(branded)))]

    names = {d["drug"] for d in drugs}
    look = []
    for a, b in LOOK_ALIKE:
        if a in names and b in names:
            for drug, partner in ((a, b), (b, a)):
                for s in LOOK_ALIKE_SECTIONS:
                    look.append({"set": "look-alike", "q": QUESTIONS[s].format(d=drug),
                                 "drug": drug, "section": s, "partner": partner})
    return generic + brand + look


def drug_of(source: str) -> str | None:
    if not source.startswith(PREFIX):
        return None
    return source[len(PREFIX):].split(" — ")[0]


def run(mode: str, q: dict, qvec: list[float], k: int) -> list[str]:
    if mode == "bm25":
        hits = es_search.bm25_search(q["q"], k)
    elif mode == "knn":
        hits = es_search.knn_search(qvec, k)
    else:
        hits = es_search.hybrid_search(q["q"], qvec, k)
    return [h["source"] for h in hits]


def score(queries: list[dict], vecs: list[list[float]], mode: str) -> list[dict]:
    rows = []
    for q, v in zip(queries, vecs):
        target = source_name(q["drug"], q["section"])
        top3 = run(mode, q, v, K)
        top10 = run(mode, q, v, 10)
        rank = next((i + 1 for i, s in enumerate(top10) if s == target), None)
        rows.append({
            "set": q["set"],
            "drug@3": any(drug_of(s) == q["drug"] for s in top3),
            "section@3": target in top3,
            "rr": 1 / rank if rank else 0.0,
            "partner@1": bool(q.get("partner")) and bool(top3) and drug_of(top3[0]) == q["partner"],
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    return {"n": n,
            "drug@3": sum(r["drug@3"] for r in rows) / n,
            "section@3": sum(r["section@3"] for r in rows) / n,
            "mrr@10": sum(r["rr"] for r in rows) / n,
            "partner@1": sum(r["partner@1"] for r in rows) / n}


def main() -> None:
    drugs = load_drugs()
    queries = build_queries(drugs)
    embedder = get_embedder()
    vecs = [embedder.embed_query(q["q"]) for q in queries]
    n_chunks = es_search.get_es().count(index=es_search.INDEX, query={"prefix": {"source": PREFIX}})["count"]
    print(f"corpus: {len(drugs)} drugs, {sum(len(d['sections']) for d in drugs)} section documents, "
          f"{n_chunks} chunks in ES")
    print(f"queries: {len(queries)} ({', '.join(f'{s}={sum(q['set'] == s for q in queries)}' for s in ('generic', 'brand', 'look-alike'))})\n")

    results = {}
    for mode in ("bm25", "knn", "hybrid"):
        rows = score(queries, vecs, mode)
        results[mode] = {s: summarize([r for r in rows if r["set"] == s]) for s in ("generic", "brand", "look-alike")}
        results[mode]["all"] = summarize(rows)

    header = f"{'set':<11} {'mode':<7} {'n':>4} {'drug@3':>7} {'section@3':>10} {'MRR@10':>7} {'partner@1':>10}"
    print(header)
    print("-" * len(header))
    for s in ("generic", "brand", "look-alike", "all"):
        for mode in ("bm25", "knn", "hybrid"):
            m = results[mode][s]
            partner = f"{m['partner@1']:.2f}" if s == "look-alike" else ""
            print(f"{s:<11} {mode:<7} {m['n']:>4} {m['drug@3']:>7.2f} {m['section@3']:>10.2f} "
                  f"{m['mrr@10']:>7.2f} {partner:>10}")
        print()

    out = Path(__file__).parent / "results" / "retrieval_fda.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"k": K, "seed": SEED, "chunks": n_chunks, "queries": len(queries),
                               "results": results}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
