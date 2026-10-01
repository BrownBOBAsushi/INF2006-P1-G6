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
- **The 300-label draft was written by an AI assistant (Claude, 2026-09-20) from the criteria above, before
  any model output existed.** A team member later supplied a 90-row file for P06-P08. Its associated log
  records a blind-labelling process, but the blinding and independence have not been independently verified.
  The original file is preserved as `data/evaluation_reviewed_subset/labels_human.csv`.
- Following the first scoring of that file, a rubric inconsistency was identified for P06-J29: the submitted
  label was 2 although the profile showed no technical-writing evidence and the fixed keyword-trap rule
  requires 0. At the user's direction, an AI-assisted audit copy was created on 2026-10-01 with only that
  pair changed to 0. `labels_audited.csv` is a post-result correction, not a new independent human label,
  review, or ratification. Both original and audited results are reported separately in
  `evidence/test-data-ai.md`.
- The 90-row subset and its audited copy do not constitute human ground truth for all 300 pairs. Metrics are
  provisional, and the evaluator itself does not authenticate label provenance.
- The P06-J29 correction was made after the original subset evaluation. Its stated basis is the fixed keyword-trap
  criterion and the profile/job evidence, not the resulting metric values; because it is post-result, it is not a
  blind label. The source human-submitted file was left unchanged.

## Review and audit record

The supplied 90-row file, the process as recorded, and the post-result rubric audit are documented in
`data/evaluation/LABEL_REVIEW_LOG.md`. The submission is retained unchanged; the correction and its metrics
are maintained separately. No claim of independently verified blind review is made. The manifest remains
`PARTIAL` for the 90/300 coverage and does not describe the audit copy as additional human review.
