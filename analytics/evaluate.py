#!/usr/bin/env python
"""Offline evaluation harness for resume-to-internship ranking.

    python analytics/evaluate.py --fixtures data/evaluation

Compares the contract's requirement-level embedding ranking against two baselines
(keyword/BM25 and pooled-chunk embedding, plus a truncating whole-resume variant)
on synthetic, pre-labelled fixtures, for one or more embedding models. Local models
only: no hosted LLM, no API keys, no network calls except the one-time download of
the pinned model weights from the Hugging Face Hub.

The protocol (metric definitions, split, method definitions) is in
data/evaluation/README.md and was fixed before the first model run. Nothing in this
script is tuned on the held-out subset; use --subset development while debugging.
This script reports measured scores only and expresses no preference between models.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import logging
import math
import platform
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

# --- fixed parameters (see MVP_PRD.md "Matching behaviour" and data/evaluation/README.md) ---
MAX_TOKENS = 240                # tokenizer tokens per chunk/requirement text, incl. heading + special tokens
MAX_CHUNKS_PER_PROFILE = 100    # DATA_API_CONTRACT safety cap; overflow is an error, never silently dropped
TOP_K = 5
BM25_K1, BM25_B = 1.5, 0.75     # unmodified textbook defaults; not tuned
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
PINNED_REVISIONS = {
    "sentence-transformers/all-MiniLM-L6-v2": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    "BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
}
SPLITS = ("development", "held_out")

METHODS = {
    "requirement_level": "Requirement-level (contract method)",
    "keyword_bm25": "Baseline A: keyword / BM25",
    "pooled_chunk": "Baseline B: pooled-chunk embedding",
    "whole_resume_truncated": "Baseline B2: whole-resume vector (TRUNCATES)",
}

STOPWORDS = frozenset("""a about above after all also an and any are as at be been being but by can could do does
during each for from had has have having he her here his how i if in into is it its just more most must no nor not of
on once only or other our out over own same she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you your
etc eg ie per via""".split())


# ------------------------------------------------------------------ fixtures

class FixtureError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load_fixtures(fixtures_dir: Path, labels_path: Path) -> dict:
    jobs_p, prof_p = fixtures_dir / "jobs.json", fixtures_dir / "profiles.json"
    manifest_p = fixtures_dir / "manifest.json"
    jobs_doc = json.loads(jobs_p.read_text(encoding="utf-8"))
    prof_doc = json.loads(prof_p.read_text(encoding="utf-8"))
    if jobs_doc.get("schema_version") != 1:
        raise FixtureError("jobs.json: schema_version must be 1")
    jobs = {}
    for j in jobs_doc["jobs"]:
        jid = j["source_job_id"]
        if jid in jobs:
            raise FixtureError(f"duplicate job {jid}")
        if j["source"] != "SYNTHETIC":
            raise FixtureError(f"{jid}: only SYNTHETIC jobs are allowed in evaluation fixtures")
        reqs = j["requirements"]
        if not 1 <= len(reqs) <= 30 or not any(r["importance"] == "REQUIRED" for r in reqs):
            raise FixtureError(f"{jid}: needs 1-30 requirements with at least one REQUIRED")
        desc = _norm_ws(j["description"])
        for r in reqs:
            if _norm_ws(r["source_quote"]) not in desc:
                raise FixtureError(f"{jid}: source_quote not found in description: {r['source_quote']!r}")
            if len(r["alternatives"]) > 10 or len(r["requirement_text"]) > 2000:
                raise FixtureError(f"{jid}: requirement bounds exceeded")
        jobs[jid] = j
    profiles = {}
    for p in prof_doc["profiles"]:
        if p["split"] not in SPLITS:
            raise FixtureError(f"{p['profile_id']}: bad split {p['split']!r}")
        profiles[p["profile_id"]] = p
    labels: dict[str, dict[str, int]] = defaultdict(dict)
    with labels_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pid, jid = row["profile_id"], row["job_id"]
            if pid not in profiles or jid not in jobs:
                raise FixtureError(f"label for unknown pair {pid},{jid}")
            if row["relevance"] not in ("0", "1", "2"):
                raise FixtureError(f"{pid},{jid}: relevance must be 0, 1 or 2 (got {row['relevance']!r})")
            if row["split"] != profiles[pid]["split"]:
                raise FixtureError(f"{pid},{jid}: split in labels does not match profiles.json")
            if jid in labels[pid]:
                raise FixtureError(f"duplicate label {pid},{jid}")
            labels[pid][jid] = int(row["relevance"])
    for pid in profiles:
        missing = set(jobs) - set(labels[pid])
        if missing:
            raise FixtureError(f"{pid}: {len(missing)} unlabelled jobs, e.g. {sorted(missing)[:3]}")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    return {
        "jobs": jobs, "profiles": profiles, "labels": dict(labels), "manifest": manifest,
        "sha256": {"jobs.json": sha256_file(jobs_p), "profiles.json": sha256_file(prof_p),
                   labels_path.name: sha256_file(labels_path)},
    }


# ------------------------------------------------------------------ chunking (no silent truncation)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


class TokenCounter:
    """Counts tokenizer tokens including special tokens, with truncation disabled."""

    def __init__(self, hf_tokenizer):
        self.tok = hf_tokenizer
        self.tok.model_max_length = 1_000_000  # only silences the length warning; we never truncate

    def count(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=True, truncation=False)["input_ids"])


class ChunkTooLong(RuntimeError):
    pass


def split_units(text: str) -> list[str]:
    """Bullets/lines first, then sentences."""
    units: list[str] = []
    for line in text.splitlines():
        line = _BULLET.sub("", line).strip()
        if line:
            units.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
    return units


def _render(heading: str, units: list[str]) -> str:
    return heading + "\n" + " ".join(units)


def _hard_split(counter: TokenCounter, heading: str, unit: str, max_tokens: int) -> list[str]:
    """Split one over-long sentence at token boundaries so heading + piece fits max_tokens."""
    overhead = counter.count(_render(heading, [""]))
    window = max_tokens - overhead
    if window < 8:
        raise ChunkTooLong(f"heading {heading!r} leaves no room in a {max_tokens}-token budget")
    enc = counter.tok(unit, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    offs = enc["offset_mapping"]
    n, start, pieces = len(offs), 0, []
    while start < n:
        w = window
        while True:
            end = min(start + w, n)
            c0 = offs[start][0]
            c1 = len(unit) if end == n else offs[end][0]
            piece = unit[c0:c1].strip()
            if counter.count(_render(heading, [piece])) <= max_tokens:
                break
            w -= 1
            if w < 1:
                raise ChunkTooLong("cannot fit a single token")
        pieces.append(piece)
        start = end
    return pieces


def chunk_entry(counter: TokenCounter, heading: str, body: str, technologies=(), max_tokens=MAX_TOKENS) -> list[str]:
    """One entry -> chunks, each = heading + consecutive units, <= max_tokens tokens. Raises rather than truncates."""
    units = split_units(body)
    if technologies:
        units.append("Technologies: " + ", ".join(technologies) + ".")
    if not units:
        return []
    chunks: list[list[str]] = []
    cur: list[str] = []
    for unit in units:
        pieces = [unit] if counter.count(_render(heading, [unit])) <= max_tokens \
            else _hard_split(counter, heading, unit, max_tokens)
        for piece in pieces:
            if cur and counter.count(_render(heading, cur + [piece])) > max_tokens:
                chunks.append(cur)
                cur = []
            cur.append(piece)
    if cur:
        chunks.append(cur)
    texts = [_render(heading, c) for c in chunks]
    for t in texts:
        if counter.count(t) > max_tokens:
            raise ChunkTooLong(f"chunk exceeds {max_tokens} tokens: {t[:60]!r}")
    return texts


def chunk_profile(counter: TokenCounter, content: dict) -> list[dict]:
    """Projects and experience only (contract); education and skills are not embedded."""
    out: list[dict] = []
    for section, key, label in (("PROJECT", "projects", "Project"), ("EXPERIENCE", "experience", "Experience")):
        for ei, entry in enumerate(content.get(key, [])):
            texts = chunk_entry(counter, f"{label}: {entry['title']}", entry["description"], entry.get("technologies", ()))
            out.extend({"section": section, "entry_index": ei, "chunk_index": ci, "text": t} for ci, t in enumerate(texts))
    if len(out) > MAX_CHUNKS_PER_PROFILE:
        raise ChunkTooLong(f"{len(out)} chunks exceeds the {MAX_CHUNKS_PER_PROFILE}-chunk cap; shorten the content")
    return out


def chunk_job(counter: TokenCounter, job: dict) -> list[str]:
    return chunk_entry(counter, f"Job: {job['title']}", job["description"])


def whole_resume_text(content: dict) -> str:
    parts = ["Skills: " + ", ".join(content.get("skills", [])) + "."]
    for label, key in (("Project", "projects"), ("Experience", "experience")):
        for e in content.get(key, []):
            tech = f" Technologies: {', '.join(e['technologies'])}." if e.get("technologies") else ""
            parts.append(f"{label}: {e['title']}. {e['description']}{tech}")
    for e in content.get("education", []):
        parts.append(f"Education: {e['qualification']}. {e.get('details', '')}".strip())
    return "\n".join(parts)


# ------------------------------------------------------------------ keyword baseline (BM25)

def keyword_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9+#]*", text.lower()) if t not in STOPWORDS]


def bm25_rank_scores(query_terms: set[str], docs: dict[str, list[str]]) -> dict[str, float]:
    n = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n
    df: Counter = Counter()
    for d in docs.values():
        df.update(set(d))
    scores = {}
    for jid, d in docs.items():
        tf, s = Counter(d), 0.0
        for t in query_terms:
            f = tf.get(t, 0)
            if f:
                idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1.0)
                s += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * len(d) / avgdl))
        scores[jid] = s
    return scores


# ------------------------------------------------------------------ metrics

def rank_jobs(scores: dict[str, float]) -> list[str]:
    """Score descending, job_id ascending on ties (DATA_API_CONTRACT)."""
    return sorted(scores, key=lambda j: (-scores[j], j))


def precision_at_k(ranked: list[str], labels: dict[str, int], k: int, min_rel: int) -> float:
    return sum(labels[j] >= min_rel for j in ranked[:k]) / k


def ndcg_at_k(ranked: list[str], labels: dict[str, int], k: int) -> float:
    def dcg(gains):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = dcg(sorted(labels.values(), reverse=True)[:k])
    return dcg([labels[j] for j in ranked[:k]]) / ideal if ideal else 0.0


def precision_ceiling(labels: dict[str, int], k: int, min_rel: int) -> float:
    return min(k, sum(v >= min_rel for v in labels.values())) / k


# ------------------------------------------------------------------ embedding

class Embedder:
    def __init__(self, name: str, revision: str):
        from sentence_transformers import SentenceTransformer
        from transformers import AutoTokenizer
        import torch
        torch.set_num_threads(1)  # conservative, as in ARCHITECTURE.md
        self.name, self.revision = name, revision
        self.model = SentenceTransformer(name, revision=revision, device="cpu")
        if getattr(self.model, "default_prompt_name", None):
            raise RuntimeError(f"{name} would apply a default prompt implicitly; refusing (use --requirement-prefix explicitly)")
        self.default_max_len = int(self.model.max_seq_length)
        dim_fn = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = int(dim_fn())
        self.counter = TokenCounter(AutoTokenizer.from_pretrained(name, revision=revision))
        self._cache: dict[tuple[str, int], np.ndarray] = {}

    def encode(self, texts: list[str], max_len: int) -> np.ndarray:
        """Unit-normalised vectors. max_len is the encoder's truncation limit for this call."""
        todo = [t for t in dict.fromkeys(texts) if (t, max_len) not in self._cache]
        if todo:
            self.model.max_seq_length = max_len
            vecs = self.model.encode(todo, batch_size=16, normalize_embeddings=True, convert_to_numpy=True,
                                     show_progress_bar=False)
            for t, v in zip(todo, vecs):
                self._cache[(t, max_len)] = v.astype(np.float64)
        return np.stack([self._cache[(t, max_len)] for t in texts])

    def encode_checked(self, texts: list[str]) -> np.ndarray:
        """Encode with the 240-token contract limit, proving beforehand that nothing will be truncated."""
        for t in texts:
            if self.counter.count(t) > MAX_TOKENS:
                raise ChunkTooLong(f"text exceeds {MAX_TOKENS} tokens: {t[:60]!r}")
        return self.encode(texts, MAX_TOKENS)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if not np.isfinite(n) or n == 0:
        raise RuntimeError("zero or non-finite vector")
    return v / n


def score_model(emb: Embedder, fx: dict, profile_ids: list[str], requirement_prefix: str) -> dict:
    jobs, profiles = fx["jobs"], fx["profiles"]
    job_ids = sorted(jobs)
    # job-side artefacts
    req_vecs: dict[str, list[np.ndarray]] = {}
    for jid in job_ids:
        mats = []
        for r in jobs[jid]["requirements"]:
            if r["importance"] != "REQUIRED":
                continue
            texts = [requirement_prefix + a for a in (r["alternatives"] or [r["requirement_text"]])]
            mats.append(emb.encode_checked(texts))
        req_vecs[jid] = mats
    job_chunks = {jid: chunk_job(emb.counter, jobs[jid]) for jid in job_ids}
    job_pooled = {jid: _unit(emb.encode_checked(job_chunks[jid]).mean(axis=0)) for jid in job_ids}
    job_text = {jid: f"{jobs[jid]['title']}\n{jobs[jid]['description']}" for jid in job_ids}
    job_tok_len = {jid: emb.counter.count(job_text[jid]) for jid in job_ids}
    job_whole = dict(zip(job_ids, emb.encode([job_text[j] for j in job_ids], emb.default_max_len)))

    scores = {m: {} for m in METHODS if m != "keyword_bm25"}
    diag = {"chunks": {}, "entries_split": {}, "max_chunk_tokens": 0, "whole_resume_tokens": {}, "mean_requirement_score": {}}
    for pid in profile_ids:
        content = profiles[pid]["content"]
        chunks = chunk_profile(emb.counter, content)
        if not chunks:
            raise FixtureError(f"{pid}: no matchable chunks (skills-only profile)")
        texts = [c["text"] for c in chunks]
        cm = emb.encode_checked(texts)
        diag["chunks"][pid] = len(chunks)
        per_entry = Counter((c["section"], c["entry_index"]) for c in chunks)
        diag["entries_split"][pid] = sum(n > 1 for n in per_entry.values())
        diag["max_chunk_tokens"] = max(diag["max_chunk_tokens"], max(emb.counter.count(t) for t in texts))
        pooled = _unit(cm.mean(axis=0))
        rtext = whole_resume_text(content)
        diag["whole_resume_tokens"][pid] = emb.counter.count(rtext)
        rvec = emb.encode([rtext], emb.default_max_len)[0]
        req, pool, whole = {}, {}, {}
        for jid in job_ids:
            per_req = [float((a @ cm.T).max()) for a in req_vecs[jid]]
            req[jid] = float(np.mean(per_req))
            pool[jid] = float(pooled @ job_pooled[jid])
            whole[jid] = float(rvec @ job_whole[jid])
        scores["requirement_level"][pid] = req
        scores["pooled_chunk"][pid] = pool
        scores["whole_resume_truncated"][pid] = whole
        diag["mean_requirement_score"][pid] = float(np.mean(list(req.values())))
    diag["jobs_split"] = sum(len(c) > 1 for c in job_chunks.values())
    diag["job_tokens_over_limit"] = sum(n > emb.default_max_len for n in job_tok_len.values())
    diag["jobs_total"] = len(job_ids)
    diag["job_token_max"] = max(job_tok_len.values())
    diag["default_max_seq_length"] = emb.default_max_len
    diag["resumes_over_limit"] = sum(n > emb.default_max_len for n in diag["whole_resume_tokens"].values())
    return {"scores": scores, "diagnostics": diag}


def score_keyword(fx: dict, profile_ids: list[str]) -> dict:
    jobs, profiles = fx["jobs"], fx["profiles"]
    docs = {jid: keyword_tokens(f"{j['title']} {j['description']}") for jid, j in jobs.items()}
    out = {}
    for pid in profile_ids:
        q = set(keyword_tokens(whole_resume_text(profiles[pid]["content"])))
        out[pid] = bm25_rank_scores(q, docs)
    return out


# ------------------------------------------------------------------ evaluation + reporting

def evaluate_scores(all_scores: dict, fx: dict, subset_profiles: dict[str, list[str]]) -> dict:
    labels = fx["labels"]
    res = {}
    for subset, pids in subset_profiles.items():
        if not pids:
            continue
        res[subset] = {"n_profiles": len(pids), "methods": {}, "ceiling": {
            "p5_strict": float(np.mean([precision_ceiling(labels[p], TOP_K, 2) for p in pids])),
            "p5_lenient": float(np.mean([precision_ceiling(labels[p], TOP_K, 1) for p in pids]))}}
        for m, per_profile in all_scores.items():
            rows = {}
            for pid in pids:
                ranked = rank_jobs(per_profile[pid])
                rows[pid] = {"p5_strict": precision_at_k(ranked, labels[pid], TOP_K, 2),
                             "p5_lenient": precision_at_k(ranked, labels[pid], TOP_K, 1),
                             "ndcg5": ndcg_at_k(ranked, labels[pid], TOP_K),
                             "top5": [(j, labels[pid][j]) for j in ranked[:TOP_K]]}
            res[subset]["methods"][m] = {
                "p5_strict": float(np.mean([r["p5_strict"] for r in rows.values()])),
                "p5_lenient": float(np.mean([r["p5_lenient"] for r in rows.values()])),
                "ndcg5": float(np.mean([r["ndcg5"] for r in rows.values()])),
                "per_profile": rows}
    return res


def score_by_label(all_scores: dict, fx: dict, subset_profiles: dict[str, list[str]], method: str) -> dict:
    out = {}
    for subset, pids in subset_profiles.items():
        buckets = defaultdict(list)
        for pid in pids:
            for jid, s in all_scores[method][pid].items():
                buckets[fx["labels"][pid][jid]].append(s)
        out[subset] = {lab: (float(np.mean(v)), len(v)) for lab, v in sorted(buckets.items())}
    return out


def _f(x: float) -> str:
    return f"{x:.3f}"


def format_report(run: dict) -> str:
    L: list[str] = []
    a = L.append
    models = list(run["models"])
    meta = run["meta"]
    a("# AI/data evaluation report")
    a("")
    a(f"Generated {meta['generated_utc']} by `analytics/evaluate.py` (script sha256 `{meta['script_sha256'][:12]}`, "
      f"git `{meta['git_commit'][:10]}`{' + uncommitted changes' if meta['git_dirty'] else ''}).")
    a("")
    if meta["label_status_banner"]:
        a(f"> **{meta['label_status_banner']}**")
        a("")
    a(f"Subset(s) evaluated: **{', '.join(run['subsets_run'])}**. Labels: `{meta['labels_file']}`. "
      f"Fixtures: {meta['n_jobs']} jobs, {meta['n_profiles_total']} profiles; sha256 " +
      ", ".join(f"{k} `{v[:12]}`" for k, v in meta["fixture_sha256"].items()) + ".")
    a("")
    for m in models:
        mm = run["models"][m]["meta"]
        a(f"- Model `{m}` revision `{mm['revision']}`, {mm['dim']} dimensions, default max_seq_length {mm['default_max_seq_length']}; "
          f"requirement prefix: {mm['requirement_prefix']!r}; wall time {mm['seconds']:.1f}s.")
    a(f"- Environment: Python {meta['python']}, {meta['platform']}, {meta['cpu']}; torch threads 1; packages: " +
      ", ".join(f"{k} {v}" for k, v in meta["packages"].items()) + ".")
    a("")
    for subset in run["subsets_run"]:
        title = {"development": "Development subset (debugging only, NOT the reported result)",
                 "held_out": "HELD-OUT subset (the reported result)"}[subset]
        a(f"## {title}")
        first = run["models"][models[0]]["metrics"][subset]
        a(f"{first['n_profiles']} profiles x {meta['n_jobs']} jobs. Ceilings: strict P@5 {_f(first['ceiling']['p5_strict'])}, "
          f"lenient P@5 {_f(first['ceiling']['p5_lenient'])}, NDCG@5 1.000. Small sample: point estimates only.")
        a("")
        header = "| Method | " + " | ".join(f"{m.split('/')[-1]}: P@5 strict / lenient / NDCG@5" for m in models) + " |"
        a(header)
        a("|---|" + "---|" * len(models))
        for key, label in METHODS.items():
            cells = []
            for m in models:
                r = run["models"][m]["metrics"][subset]["methods"][key]
                cells.append(f"{_f(r['p5_strict'])} / {_f(r['p5_lenient'])} / {_f(r['ndcg5'])}")
            a(f"| {label} | " + " | ".join(cells) + " |")
        a("")
        a("Baseline A uses no embedding model, so its row is identical across models by construction.")
        a("")
        for m in models:
            met = run["models"][m]["metrics"][subset]["methods"]
            a(f"### Per-profile, `{m.split('/')[-1]}` ({subset}): strict P@5 / NDCG@5")
            a("")
            pids = list(next(iter(met.values()))["per_profile"])
            diag = run["models"][m]["diagnostics"]
            a("| Profile | Chunks | " + " | ".join(METHODS[k].split(":")[0] for k in METHODS) + " |")
            a("|---|---|" + "---|" * len(METHODS))
            for pid in pids:
                cells = [f"{_f(met[k]['per_profile'][pid]['p5_strict'])} / {_f(met[k]['per_profile'][pid]['ndcg5'])}" for k in METHODS]
                a(f"| {pid} | {diag['chunks'].get(pid, '-')} | " + " | ".join(cells) + " |")
            a("")
            a("Top-5 ranked jobs as `job(label)`:")
            a("")
            for pid in pids:
                for k in METHODS:
                    top = " ".join(f"{j}({l})" for j, l in met[k]["per_profile"][pid]["top5"])
                    a(f"- {pid} {METHODS[k].split(':')[0]}: {top}")
            a("")
    a("## Diagnostics")
    a("")
    for m in models:
        d = run["models"][m]["diagnostics"]
        a(f"### `{m}`")
        a("")
        a(f"- Largest chunk: {d['max_chunk_tokens']} tokens (limit {MAX_TOKENS}, including heading and special tokens); "
          f"no chunk or requirement text was truncated (the harness raises otherwise).")
        a(f"- Chunks per profile: " + ", ".join(f"{p}={n}" for p, n in d["chunks"].items()) + ".")
        a(f"- Entries that needed sentence/token splitting: {sum(d['entries_split'].values())} profile entries and "
          f"{d['jobs_split']} jobs. If 0, the splitter was not exercised by these fixtures (it is covered by unit tests only).")
        a(f"- Baseline B2 truncation at the encoder's default {d['default_max_seq_length']} tokens: "
          f"{d['resumes_over_limit']}/{len(d['whole_resume_tokens'])} whole-resume inputs and "
          f"{d['job_tokens_over_limit']}/{d['jobs_total']} job inputs exceeded the limit and were truncated "
          f"(longest job {d['job_token_max']} tokens; whole-resume token counts: " +
          ", ".join(f"{p}={n}" for p, n in d["whole_resume_tokens"].items()) + ").")
        a("- Mean requirement-level job score per profile (length-bias check against chunk count): " +
          ", ".join(f"{p}={_f(s)}" for p, s in d["mean_requirement_score"].items()) + ".")
        for method in ("requirement_level", "pooled_chunk"):
            sbl = run["models"][m]["score_by_label"][method]
            for subset, byl in sbl.items():
                a(f"- Mean {method} score by label ({subset}): " +
                  ", ".join(f"label {lab}={_f(mean)} (n={n})" for lab, (mean, n) in byl.items()) + ".")
        a("")
    a("## Limitations (read before quoting these numbers)")
    a("")
    a("- Fixtures and labels were authored by one AI author; label review by a human team member is pending unless the banner above says otherwise.")
    a("- Job requirements are hand-authored (no extraction errors); only the requirement-level method sees them.")
    a("- 5 profiles per subset. No confidence intervals or significance claims. Scores are internal similarities, not probabilities of suitability.")
    a("- Baseline B2 truncates its inputs by design and is not an equivalent full-context encoder.")
    a("- Synthetic text is cleaner than real resumes; results do not transfer to real data without further evaluation.")
    a("- This report expresses no preference between models; that decision belongs to the team.")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ main

def _pkg_versions() -> dict:
    from importlib.metadata import version
    return {p: version(p) for p in ("sentence-transformers", "transformers", "torch", "numpy", "tokenizers")}


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).resolve().parent).stdout.strip()
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixtures", required=True, type=Path, help="directory with jobs.json, profiles.json, labels.csv")
    ap.add_argument("--labels", type=Path, help="labels CSV (default: <fixtures>/labels.csv)")
    ap.add_argument("--model", action="append", help=f"embedding model name; repeatable (default: {DEFAULT_MODEL})")
    ap.add_argument("--revision", action="append", help="revision for a model not in the pinned table (one per --model, in order)")
    ap.add_argument("--subset", choices=("development", "held_out", "both"), default="both",
                    help="use 'development' while debugging: held-out profiles are then never scored")
    ap.add_argument("--requirement-prefix", default="",
                    help="text prepended to requirement texts only (e.g. a query instruction); default none")
    ap.add_argument("--out-dir", type=Path, help="write results JSON and Markdown report here")
    ap.add_argument("--tag", default="", help="suffix for output file names")
    args = ap.parse_args(argv)

    models = args.model or [DEFAULT_MODEL]
    revisions = []
    extra = list(args.revision or [])
    for m in models:
        if m in PINNED_REVISIONS:
            revisions.append(PINNED_REVISIONS[m])
        elif extra:
            revisions.append(extra.pop(0))
        else:
            ap.error(f"no pinned revision for {m!r}; pass --revision <commit sha> (unpinned models are not allowed)")

    fixtures_dir = args.fixtures
    labels_path = args.labels or fixtures_dir / "labels.csv"
    fx = load_fixtures(fixtures_dir, labels_path)
    subsets_run = list(SPLITS) if args.subset == "both" else [args.subset]
    subset_profiles = {s: sorted(p for p, v in fx["profiles"].items() if v["split"] == s) for s in subsets_run}
    profile_ids = [p for s in subsets_run for p in subset_profiles[s]]

    default_labels = labels_path.resolve() == (fixtures_dir / "labels.csv").resolve()
    review = (fx["manifest"].get("label_review") or {}).get("status", "UNKNOWN")
    if not default_labels:
        banner = f"Custom label file {labels_path.name}: provenance/review status is not verified by this script."
    elif review != "COMPLETED":
        banner = ("PROVISIONAL: labels are AI-drafted and have NOT been reviewed by a human team member "
                  f"(manifest label_review.status = {review}). These are not yet human ground truth.")
    else:
        banner = ""
    if args.subset == "development":
        banner = (banner + " " if banner else "") + "Development subset only: this is debugging output, not a result."

    kw_scores = score_keyword(fx, profile_ids)
    run = {"models": {}, "subsets_run": subsets_run, "meta": {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script_sha256": sha256_file(Path(__file__)),
        "git_commit": _git("rev-parse", "HEAD"), "git_dirty": bool(_git("status", "--porcelain", "--", ".", ":!evidence")),
        "python": platform.python_version(), "platform": platform.platform(), "cpu": platform.processor() or platform.machine(),
        "packages": _pkg_versions(), "fixture_sha256": fx["sha256"], "labels_file": str(labels_path.name),
        "n_jobs": len(fx["jobs"]), "n_profiles_total": len(fx["profiles"]), "label_status_banner": banner,
        "args": {"subset": args.subset, "models": models, "requirement_prefix": args.requirement_prefix}}}

    for name, rev in zip(models, revisions):
        t0 = time.time()
        emb = Embedder(name, rev)
        scored = score_model(emb, fx, profile_ids, args.requirement_prefix)
        all_scores = {"keyword_bm25": kw_scores, **scored["scores"]}
        all_scores = {k: all_scores[k] for k in METHODS}
        run["models"][name] = {
            "meta": {"revision": rev, "dim": emb.dim, "default_max_seq_length": emb.default_max_len,
                     "requirement_prefix": args.requirement_prefix, "seconds": time.time() - t0},
            "metrics": evaluate_scores(all_scores, fx, subset_profiles),
            "diagnostics": scored["diagnostics"],
            "score_by_label": {m: score_by_label(all_scores, fx, subset_profiles, m) for m in ("requirement_level", "pooled_chunk")},
            "scores": {m: {p: {j: round(s, 6) for j, s in d.items()} for p, d in per.items()} for m, per in all_scores.items()},
        }

    report = format_report(run)
    print(report)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d")
        stem = f"data-ai-eval-{stamp}" + (f"-{args.tag}" if args.tag else "")
        (args.out_dir / f"{stem}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        (args.out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
        print(f"wrote {args.out_dir / (stem + '.json')} and {args.out_dir / (stem + '.md')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    logging.getLogger("transformers").setLevel(logging.ERROR)
    sys.exit(main())
