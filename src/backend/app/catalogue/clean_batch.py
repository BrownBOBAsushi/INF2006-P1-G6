#!/usr/bin/env python3
"""Clean a candidate fetch_live_jobs.py batch offline for human review.

    python clean_batch.py --in data/live_batch.json --out data/live_batch_clean.json

Re-derives plain-text description, requirements, eligibility notes, country code, and company name without network
access. Ambiguous compound skill clauses cause the whole record to be skipped for manual review. The sidecar is marked
PENDING_HUMAN_PROVENANCE_REVIEW; cleaning does not grant permission to collect, store, display, or redistribute data.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import fetch_live_jobs as f
except ImportError:  # direct `python clean_batch.py` invocation
    import fetch_live_jobs as f


def clean_job(j: dict, allow_non_english: bool) -> tuple[dict | None, str | None]:
    company = f.normalise_ws(j["company_name"])
    if company.lower() in f.INTERMEDIARIES:
        return None, "intermediary_not_employer"
    company = f._PUBLISHER_SUFFIX_RX.sub("", company).strip() or company
    desc = f.strip_html(j["description"])
    if not desc:
        return None, "empty_description"
    if not allow_non_english and f.looks_non_english(desc):
        return None, "non_english"
    reqs, ambiguous = f.extract_job_requirements(desc)
    if ambiguous:
        return None, "manual_review_ambiguous_requirements"
    if not reqs:
        return None, "no_requirements_section"
    job_type = j["job_type"]
    downgraded = False
    if job_type == "INTERNSHIP" and f.classify_description_job_type(desc) != "INTERNSHIP":
        job_type, downgraded = "UNKNOWN", True
    out = dict(j)
    out.update({
        "company_name": company, "description": desc, "job_type": job_type,
        "country_code": f.guess_country_code(j["location"]),
        "eligibility_notes": f.extract_eligibility_notes(desc),
        "requirements": [r.to_dict() for r in reqs],
    })
    return out, ("job_type_downgraded" if downgraded else None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-non-english", action="store_true")
    a = ap.parse_args()
    src = json.loads(a.inp.read_text("utf-8"))
    stats: Counter = Counter()
    jobs = []
    for j in src["jobs"]:
        new, note = clean_job(j, a.allow_non_english)
        if new is None:
            stats[note] += 1
            continue
        if note:
            stats[note] += 1
        jobs.append(new)
    if not jobs:
        print("nothing left after cleaning", dict(stats), file=sys.stderr)
        return 1
    a.out.write_text(json.dumps({"schema_version": 1, "jobs": jobs}, indent=2, ensure_ascii=False), "utf-8")
    prov_in = a.inp.with_suffix(".provenance.json")
    prov = json.loads(prov_in.read_text("utf-8")) if prov_in.exists() else {}
    prov.update({
        "batch_file": a.out.name, "job_count": len(jobs), "cleaned_at": datetime.now(timezone.utc).isoformat(),
        "cleaned_from": a.inp.name, "input_job_count": len(src["jobs"]), "cleaning_counts": dict(stats),
        "review_status": "PENDING_HUMAN_PROVENANCE_REVIEW",
        "transformations": [
            "HTML converted to plain text (entities decoded before tags are parsed)",
            "requirements re-derived from the listing's own section; source_quote preserves the source line; explicit "
            "two-skill OR stays one alternatives row; explicit two-skill AND becomes separate rows; ambiguous compound "
            "skill lines are dropped for review; preferred/optional/nice-to-have/advantage/plus wording = PREFERRED",
            "dropped: non-English listings, intermediary employers (" + ", ".join(sorted(f.INTERMEDIARIES)) + "), "
            "listings without a requirements section or with ambiguous compound skill clauses",
            "company_name: ATS suffix such as ' - Personio' removed",
            "job_type INTERNSHIP kept only where the description explicitly identifies the role as an internship; "
            "incidental mentions and title words do not count (provider job_types not stored in input)",
            "country_code re-derived from whole-word location match, otherwise ZZ",
        ],
    })
    a.out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False), "utf-8")
    print(f"{len(src['jobs'])} -> {len(jobs)} jobs; {dict(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
