# Relevance labelling criteria

Fixed before any embedding model or baseline was run on these fixtures (see git history: the fixtures and
this file are committed before `analytics/evaluate.py` exists).

Each (profile, job) pair has one label. Judge the pair from the profile's **projects and experience text**
(skills lists are self-reported claims and count only as weak support) against the job's **description and
required requirements**. Ignore preferred requirements, location, company, pay and eligibility notes.
Generic soft requirements (communication, teamwork) count only when the profile shows explicit evidence.
Paraphrase counts: "exposing endpoints" is evidence for "building HTTP APIs".

| Label | Meaning | Guideline |
|---|---|---|
| 2 | Relevant | Direct project/experience evidence for about two-thirds or more of the job's required requirements, **including** the requirement(s) that make up the job's central duty. A student with this profile is a credible applicant today. |
| 1 | Partly relevant | Direct evidence for at least one requirement that is central to the job (roughly a third to two-thirds of required requirements), **or** most requirements are met but the central duty is absent. Realistic stretch application with transferable capability. |
| 0 | Not relevant | Less than a third of required requirements have evidence, or the overlap is only generic or incidental (Excel, Git, communication, the word "API" in a documentation role). |

Rules of thumb used consistently:

- **Keyword traps are 0.** A job that mentions a tool the profile uses, but whose duties are elsewhere
  (for example the technical-writing job J29 mentions Python, API and Git but is a no-code writing role), is 0
  unless the profile shows evidence for the job's actual duties.
- **Negation is respected.** "No programming is required", "does not involve writing production code" describe
  the job; they do not make a coder a better fit.
- **Learning outcomes are not requirements.** Statements such as "you will learn Docker" are not required
  and do not lower a label when the profile lacks them.
- **OR groups** are met if any alternative is evidenced; **AND** conditions are separate requirements.
- **Long resumes get no credit for length.** Judge evidence, not how many entries a profile has.

## Provenance and review status

- Profiles and jobs are entirely synthetic (no real people, resumes, employers or scraped data). Company names
  are invented; URLs use the reserved `example.com` domain.
- **Labels were drafted by an AI assistant (Claude, 2026-09-20) working from the criteria above, before any
  model output existed.** They have **not yet been reviewed by a human on the team**.
  That is not the same as human ground truth. Until a team member has independently labelled the pairs, all
  results computed from these labels are provisional (the evaluation harness prints this on every run).
- No model or model-comparison output was used to write or adjust any label.

## Human review workflow (pending)

1. A team member fills the blank sheet `labelling_sheet_blank.csv` (`relevance` 0/1/2) using only this
   document, the profiles and the jobs, **without** looking at `labels.csv` rationales or any evaluation output.
2. Save it as `labels_human.csv` (same columns as `labels.csv`) and run
   `python analytics/evaluate.py --fixtures data/evaluation --labels data/evaluation/labels_human.csv`.
3. Record disagreements with the AI draft and how they were resolved in `data/evaluation/LABEL_REVIEW_LOG.md`.
   Do not change labels after seeing model rankings; if a label must change, log why and re-run everything.
4. When review is complete set `label_review.status` in `manifest.json` to `COMPLETED` with reviewer and date.
