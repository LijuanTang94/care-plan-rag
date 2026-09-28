"""Build the FDA drug-label corpus: the ~300 most common single-ingredient Rx generics, one label each.

Source: openFDA drug labels (FDA Structured Product Labeling; public domain, https://open.fda.gov).
"Most common" = most FDA labels on file for that generic name, i.e. the most manufacturers — a
reproducible proxy for how widely a drug is prescribed.

The 9 drugs that eval_generation.py uses as deliberately out-of-scope cases are excluded, so its
in-scope vs out-of-scope grounding separation still means what it says.

Output: eval/data/fda_labels.jsonl.gz — one line per drug with set_id/version/effective_time, so the
exact label versions are pinned. Run from the repo root (needs network):
    python -m eval.fetch_fda_labels
"""

import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.fda.gov/drug/label.json"
OUT = Path(__file__).parent / "data" / "fda_labels.jsonl.gz"
TARGET = 300
SECTION_CAP = 6000  # chars kept per section; the long tail of adverse-reaction tables adds bulk, not answers

# Kept in label order; each becomes its own document ("FDA label: <drug> — <title>").
SECTIONS = {
    "boxed_warning": "Boxed warning",
    "indications_and_usage": "Indications and usage",
    "dosage_and_administration": "Dosage and administration",
    "contraindications": "Contraindications",
    "warnings_and_cautions": "Warnings and precautions",
    "adverse_reactions": "Adverse reactions",
    "drug_interactions": "Drug interactions",
    "use_in_specific_populations": "Use in specific populations",
}
REQUIRED = ["indications_and_usage", "dosage_and_administration", "contraindications", "warnings_and_cautions"]

OUT_OF_SCOPE = {"warfarin", "atorvastatin", "apixaban", "sertraline", "albuterol",
                "omeprazole", "gabapentin", "hydroxychloroquine", "tamsulosin"}

SALTS = {"hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium", "maleate", "besylate",
         "mesylate", "tartrate", "succinate", "fumarate", "citrate", "sulfate", "phosphate", "acetate",
         "bromide", "hydrobromide", "dihydrate", "monohydrate", "hyclate", "bitartrate", "tromethamine",
         "extended-release", "delayed-release", "er", "xr", "and", "disodium", "dipropionate",
         "dihydrochloride", "bisulfate", "benzoate", "oxalate", "medoxomil", "propionate", "furoate",
         "axetil", "mofetil", "methylsulfate", "chloride", "carbonate", "tablets", "tablet", "capsules",
         "injection", "oral", "solution"}


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params, safe=':+"')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"results": []}
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"openFDA kept failing: {url}")


def base_name(generic: str) -> str:
    """Strip salt/release-form words, keeping the first word ("potassium chloride" stays whole)."""
    words = [w for w in re.split(r"[\s/]+", generic.lower()) if w]
    return " ".join(words[:1] + [w for w in words[1:] if w not in SALTS])


SHARED_FIRST_WORDS = {"sodium", "calcium", "potassium", "magnesium", "insulin"}


def dedupe_key(name: str) -> str:
    """One label per drug: "diclofenac epolamine" and "diclofenac topical" are both diclofenac."""
    first = name.split()[0]
    return name if first in SHARED_FIRST_WORDS else first


def brand_names(generic_exact: str, name: str) -> list[str]:
    """Brand names marketed for this generic, excluding generic-labelled products."""
    q = f'openfda.generic_name.exact:"{generic_exact}"+AND+openfda.product_type:"HUMAN PRESCRIPTION DRUG"'
    rows = _get({"search": q, "count": "openfda.brand_name.exact", "limit": 20})["results"]
    first = name.split()[0]
    return [r["term"] for r in rows if first not in r["term"].lower()][:5]


def candidate_generics() -> list[str]:
    """Generic names ranked by label count, restricted to modern (PLR-format) Rx labels."""
    q = 'openfda.product_type:"HUMAN PRESCRIPTION DRUG"+AND+_exists_:warnings_and_cautions'
    rows = _get({"search": q, "count": "openfda.generic_name.exact", "limit": 1000})["results"]
    return [r["term"] for r in rows]


def fetch_label(generic_exact: str) -> dict | None:
    q = (f'openfda.generic_name.exact:"{generic_exact}"'
         + "".join(f"+AND+_exists_:{s}" for s in REQUIRED))
    rows = _get({"search": q, "sort": "effective_time:desc", "limit": 1})["results"]
    return rows[0] if rows else None


def main() -> None:
    seen, drugs = set(), []
    for generic in candidate_generics():
        if len(drugs) >= TARGET:
            break
        if "," in generic or " AND " in generic:
            continue  # combination products
        name = base_name(generic)
        if not name or dedupe_key(name) in seen or any(o in name for o in OUT_OF_SCOPE):
            continue
        label = fetch_label(generic)
        time.sleep(0.3)  # stay under openFDA's 240 requests/minute without an API key
        if not label:
            continue
        sections = {}
        for key, title in SECTIONS.items():
            text = " ".join(label.get(key) or []).strip()
            if text:
                sections[title] = text[:SECTION_CAP]
        brands = brand_names(generic, name)
        time.sleep(0.3)
        seen.add(dedupe_key(name))
        drugs.append({
            "drug": name,
            "generic_name": generic,
            "brand_names": brands,
            "set_id": label.get("set_id"),
            "version": label.get("version"),
            "effective_time": label.get("effective_time"),
            "sections": sections,
        })
        print(f"[{len(drugs):3d}] {name}  ({len(sections)} sections)", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for d in drugs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    chars = sum(len(t) for d in drugs for t in d["sections"].values())
    docs = sum(len(d["sections"]) for d in drugs)
    print(f"wrote {len(drugs)} drugs, {docs} section documents, {chars:,} chars -> {OUT}")


if __name__ == "__main__":
    main()
