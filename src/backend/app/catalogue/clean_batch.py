#!/usr/bin/env python3
"""Clean an existing fetch_live_jobs.py batch offline, using the same rules as the patched fetcher.

    python clean_batch.py --in data/live_batch.json --out data/live_batch_clean.json

Re-derives from each stored description (no network): plain-text description, requirements (verbatim lines from the
listing's own requirements section, no placeholders), eligibility notes, country code, company name. Drops non-English
listings, intermediaries and jobs with no requirements section. job_type INTERNSHIP is kept only when the description
itself explicitly says internship/Praktikum/Werkstudent; otherwise it becomes UNKNOWN (the provider's job_types field is
not stored in the batch, so re-fetch with the patched fetcher to get provider-verified values).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import fetch_live_jobs as f

_INTERN_WORD = re.compile(r"\b(intern(?:ship)?s?|praktik\w*|werkstudent\w*|working student)\b", re.I)


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
    reqs = f.extract_requirements(desc)
    if not reqs:
        return None, "no_requirements_section"
    job_type = j["job_type"]
    downgraded = False
    if job_type == "INTERNSHIP" and not _INTERN_WORD.search(desc):
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
        "transformations": [
            "HTML converted to plain text (entities decoded before tags are parsed)",
            "requirements re-derived: lines verbatim from the listing's own requirements/qualifications/'what you bring' "
            "section; requirement_text == source_quote; preferred/nice-to-have/advantage/plus wording = PREFERRED, "
            "all others REQUIRED; no placeholder rows",
            "dropped: non-English listings, intermediary employers (" + ", ".join(sorted(f.INTERMEDIARIES)) + "), "
            "listings without a requirements section",
            "company_name: ATS suffix such as ' - Personio' removed",
            "job_type INTERNSHIP kept only where the description itself says internship/Praktikum/Werkstudent, else UNKNOWN "
            "(provider job_types not stored in the original batch)",
            "country_code re-derived from whole-word location match, otherwise ZZ",
        ],
    })
    a.out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False), "utf-8")
    print(f"{len(src['jobs'])} -> {len(jobs)} jobs; {dict(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())