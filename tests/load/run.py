#!/usr/bin/env python
"""Local load / scalability measurements for the matching pipeline. Synthetic data only; every number is measured.

    python tests/load/run.py --scenario matching-scale        # exact in-memory matcher: jobs x requirements x chunks
    python tests/load/run.py --scenario matching-concurrency  # 1/5/10/25 concurrent match requests (threads)
    python tests/load/run.py --scenario embedding-throughput  # real MiniLM: cold load, warm chunk/s
    python tests/load/run.py --scenario db-ranking-scale      # real PostgreSQL 16 + pgvector ranking query at 100..N jobs
    python tests/load/run.py --scenario all --out-dir evidence        # the four component scenarios above
    python tests/load/run.py --scenario browse-during-processing --target harness    # HTTP, via the reference harness
    python tests/load/run.py --scenario api --target http://127.0.0.1:8000 --cookie NAME=VALUE --csrf-token T --origin O
    python tests/load/run.py --scenario browse-during-processing     # no --target: NOT RUN (exit 3), no numbers

The HTTP scenarios (api-concurrency, browse-during-processing; `api` runs both) live in tests/load/api_load.py. They need a
target: `harness` (tests/load/harness_app.py, NOT the project's API) or the base URL of a running API that implements the
contract endpoints, with a test session supplied by the operator.

What this is NOT: an HTTP load test. It measures the matching computation and the database ranking query on this
machine, not the API, auth, PDF processing, network or a cloud VM. Latencies exclude resume embedding unless the
scenario says otherwise. Results depend on this hardware; see the recorded machine/version block.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "src" / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DIM = 384
SEED = 20260921
WARMUP = 3


def pct(values, p):
    return float(np.percentile(values, p)) if values else float("nan")


def summary(ms: list[float]) -> dict:
    return {"n": len(ms), "p50_ms": round(pct(ms, 50), 3), "p95_ms": round(pct(ms, 95), 3), "max_ms": round(max(ms), 3),
            "mean_ms": round(statistics.fmean(ms), 3)}


def unit_rows(rng, n):
    v = rng.normal(size=(n, DIM)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def make_catalogue(rng, n_jobs, reqs_per_job, alt_prob=0.3):
    from app.matching.scoring import JobVectors, RequirementVectors
    jobs, n_req, n_vec = [], 0, 0
    for j in range(n_jobs):
        reqs = []
        for r in range(reqs_per_job):
            k = 2 if rng.random() < alt_prob else 1
            reqs.append(RequirementVectors(f"{j}-{r}", r, "REQUIRED", f"requirement {j}-{r}", tuple(f"alt{a}" for a in range(k)),
                                           unit_rows(rng, k)))
            n_vec += k
        n_req += reqs_per_job
        jobs.append(JobVectors(f"job-{j:06d}", tuple(reqs)))
    return jobs, n_req, n_vec


def machine() -> dict:
    return {"platform": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "python": platform.python_version(),
            "numpy": np.__version__, "blas_threads_env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}}


def git_state() -> dict:
    def g(*a):
        try:
            return subprocess.run(["git", *a], capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"commit": g("rev-parse", "HEAD"), "dirty_outside_evidence": bool(g("status", "--porcelain", "--", ".", ":!evidence"))}


def rss_mb() -> float:
    return round(psutil.Process().memory_info().rss / 2**20, 1)


# ---------------------------------------------------------------------------------------------- scenarios

def scenario_matching_scale(quick: bool) -> dict:
    from app.matching.scoring import rank_jobs
    rng = np.random.default_rng(SEED)
    grid = [(30, 3, 4), (100, 4, 10), (1000, 4, 10), (1000, 4, 100), (1000, 8, 10)] if quick else \
           [(30, 3, 4), (100, 4, 4), (100, 4, 10), (1000, 3, 10), (1000, 4, 10), (1000, 8, 10), (1000, 4, 50), (1000, 4, 100),
            (5000, 4, 10), (10000, 4, 10)]
    reps = 10 if quick else 30
    rows = []
    for n_jobs, rpj, n_chunks in grid:
        jobs, n_req, n_vec = make_catalogue(rng, n_jobs, rpj)
        chunks = unit_rows(rng, n_chunks)
        for _ in range(WARMUP):
            rank_jobs(chunks, jobs)
        times, errors = [], 0
        for _ in range(reps):
            t = time.perf_counter()
            try:
                page, total, _ = rank_jobs(chunks, jobs, top_k=5)
                assert len(page) == 5 and total == n_jobs
            except Exception:  # noqa: BLE001
                errors += 1
            times.append((time.perf_counter() - t) * 1000)
        tracemalloc.start()
        rank_jobs(chunks, jobs)
        peak = tracemalloc.get_traced_memory()[1] / 2**20
        tracemalloc.stop()
        rows.append({"jobs": n_jobs, "requirements_per_job": rpj, "requirements_total": n_req, "requirement_vectors": n_vec,
                     "resume_chunks": n_chunks, "pairwise_similarities": n_vec * n_chunks, "errors": errors,
                     "throughput_queries_per_s": round(1000 / statistics.fmean(times), 2),
                     "python_alloc_peak_mb_during_query": round(peak, 2), "catalogue_vectors_mb": round(n_vec * DIM * 4 / 2**20, 2),
                     **summary(times)})
        print(f"  jobs={n_jobs:>5} reqs/job={rpj} chunks={n_chunks:>3}: p50={rows[-1]['p50_ms']} ms p95={rows[-1]['p95_ms']} ms", flush=True)
    return {"note": "exact in-memory matcher (app.matching.scoring.rank_jobs), single thread of Python, random unit vectors, "
                    f"{WARMUP} warm-up runs discarded, {reps} timed repetitions per row", "rows": rows}


def scenario_matching_concurrency(quick: bool) -> dict:
    from app.matching.scoring import rank_jobs
    rng = np.random.default_rng(SEED)
    jobs, n_req, n_vec = make_catalogue(rng, 1000, 4)
    chunks = unit_rows(rng, 10)
    rank_jobs(chunks, jobs)
    rows = []
    for conc in (1, 5, 10, 25):
        total_requests = 50 if quick else 100
        lat, errors, lock = [], 0, threading.Lock()

        def one():
            nonlocal errors
            t = time.perf_counter()
            try:
                page, _, _ = rank_jobs(chunks, jobs, top_k=5)
                assert len(page) == 5
            except Exception:  # noqa: BLE001
                with lock:
                    errors += 1
            with lock:
                lat.append((time.perf_counter() - t) * 1000)

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(lambda _: one(), range(total_requests)))
        wall = time.perf_counter() - t0
        rows.append({"concurrency": conc, "requests": total_requests, "errors": errors, "error_rate": errors / total_requests,
                     "wall_s": round(wall, 3), "throughput_req_per_s": round(total_requests / wall, 2), **summary(lat)})
        print(f"  concurrency={conc:>2}: {rows[-1]['throughput_req_per_s']} req/s p95={rows[-1]['p95_ms']} ms errors={errors}", flush=True)
    return {"note": "1,000 jobs x 4 requirements, 10 chunks; N threads calling the matcher in-process (no HTTP, no admission "
                    "control, no database). 'latency' includes waiting for the GIL/BLAS threads.", "requirement_vectors": n_vec, "rows": rows}


def scenario_embedding_throughput(quick: bool) -> dict:
    from app.processing.chunking import chunk_resume_content
    rss0 = rss_mb()
    t = time.perf_counter()
    from app.processing.embeddings import EmbeddingModel
    model = EmbeddingModel()
    load_s = time.perf_counter() - t
    profiles = json.loads((ROOT / "data" / "evaluation" / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    texts = [c["text"] for p in profiles for c in chunk_resume_content(model.counter, p["content"])]
    jobs = json.loads((ROOT / "data" / "evaluation" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    req_texts = [t for j in jobs for r in j["requirements"] for t in (r["alternatives"] or [r["requirement_text"]])]
    rows = []
    t = time.perf_counter()
    model.embed(texts[:1])                                   # first call after load ("cold")
    cold_ms = (time.perf_counter() - t) * 1000
    for label, corpus in (("resume chunks (fixture, 40-100 tokens)", texts), ("requirement texts (fixture)", req_texts)):
        reps = 3 if quick else 5
        per = []
        for _ in range(reps):
            t = time.perf_counter()
            model.embed(corpus, batch_size=16)
            per.append(time.perf_counter() - t)
        best = min(per)
        rows.append({"corpus": label, "texts": len(corpus), "reps": reps, "median_s": round(statistics.median(per), 3),
                     "texts_per_s_median": round(len(corpus) / statistics.median(per), 1), "best_s": round(best, 3)})
        print(f"  {label}: {rows[-1]['texts_per_s_median']} texts/s", flush=True)
    single = []
    for tx in texts[:20]:
        t = time.perf_counter()
        model.embed([tx])
        single.append((time.perf_counter() - t) * 1000)
    return {"note": "real all-MiniLM-L6-v2 on CPU, torch threads=1 (ARCHITECTURE.md default), local cache", "model_load_s": round(load_s, 2),
            "first_call_after_load_ms": round(cold_ms, 1), "rss_before_load_mb": rss0, "rss_after_load_and_use_mb": rss_mb(),
            "single_text_latency": summary(single), "rows": rows}


def scenario_db_ranking_scale(quick: bool) -> dict:
    import pgserver
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, insert, text
    from sqlalchemy.orm import Session

    from app.catalogue.models import Job, JobRequirement, RequirementEmbedding
    from app.db.models import ResumeChunk, ResumeProfile, User
    from app.matching.sql import rank_jobs_sql

    tmp = tempfile.mkdtemp(prefix="loadpg")
    server = pgserver.get_server(tmp, cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    os.environ["DATABASE_URL"] = url
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    version = "load-test@1"
    rng = np.random.default_rng(SEED)
    rows, done = [], 0
    sizes = [100, 1000] if quick else [100, 1000, 5000, 10000]
    n_chunks, reps = 10, (10 if quick else 30)
    with Session(engine) as db:
        uid = uuid.uuid4()
        db.add(User(user_id=uid, google_sub="load-user", resume_revision=1))
        db.flush()
        db.add(ResumeProfile(user_id=uid, revision=1, content={}, content_hash="0" * 64, embedding_version=version))
        db.flush()
        db.execute(insert(ResumeChunk), [dict(chunk_id=uuid.uuid4(), user_id=uid, profile_revision=1, section="PROJECT", entry_index=i,
                                              chunk_index=0, text="chunk", embedding=v, embedding_version=version)
                                         for i, v in enumerate(unit_rows(rng, n_chunks))])
        db.commit()
        for size in sizes:
            jobs_b, reqs_b, embs_b = [], [], []
            for n in range(done, size):
                jid = uuid.uuid4()
                jobs_b.append(dict(job_id=jid, source="SYNTHETIC", source_job_id=f"L{n}", title="t", company_name="c", country_code="SG",
                                   location="l", description="d", apply_url="https://example.com/a", source_url="https://example.com/b",
                                   job_type="INTERNSHIP", employment_time="FULL_TIME", work_arrangement="HYBRID",
                                   eligibility_notes=[], is_active=True, content_hash="0" * 64))
                for r in range(4):
                    rid, k = uuid.uuid4(), (2 if rng.random() < 0.3 else 1)
                    alts = ["a", "b"][:k] if k == 2 else []
                    reqs_b.append(dict(requirement_id=rid, job_id=jid, ordinal=r, requirement_text="r", importance="REQUIRED",
                                       alternatives=alts, source_quote="d", evidence_skills=[]))
                    for a, v in enumerate(unit_rows(rng, k)):
                        embs_b.append(dict(embedding_id=uuid.uuid4(), requirement_id=rid, alternative_index=a, text="t", embedding=v,
                                           embedding_version=version))
            t = time.perf_counter()
            db.execute(insert(Job), jobs_b)
            db.execute(insert(JobRequirement), reqs_b)
            db.execute(insert(RequirementEmbedding), embs_b)
            db.commit()
            load_s = time.perf_counter() - t
            done = size
            db.execute(text("ANALYZE"))
            db.commit()
            n_vec = db.execute(text("SELECT count(*) FROM requirement_embeddings")).scalar()
            for _ in range(WARMUP):
                rank_jobs_sql(db, user_id=uid, profile_revision=1, embedding_version=version, limit=5)
            times, errors = [], 0
            for _ in range(reps):
                t = time.perf_counter()
                try:
                    page = rank_jobs_sql(db, user_id=uid, profile_revision=1, embedding_version=version, limit=5)
                    assert len(page.rows) == 5 and page.total == size
                except Exception:  # noqa: BLE001
                    errors += 1
                    db.rollback()
                times.append((time.perf_counter() - t) * 1000)
            rows.append({"jobs": size, "requirements_total": size * 4, "requirement_vectors": int(n_vec), "resume_chunks": n_chunks,
                         "pairwise_similarities": int(n_vec) * n_chunks, "insert_seconds_for_batch": round(load_s, 2), "errors": errors,
                         "throughput_queries_per_s": round(1000 / statistics.fmean(times), 2), **summary(times)})
            print(f"  jobs={size:>6}: p50={rows[-1]['p50_ms']} ms p95={rows[-1]['p95_ms']} ms", flush=True)
        pg_version = db.execute(text("SHOW server_version")).scalar()
        vec_version = db.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
    engine.dispose()
    server.cleanup()
    return {"note": "real PostgreSQL + pgvector (embedded via pgserver, loopback, no other load), exact search, no ANN index; "
                    "the contract ranking SQL (app.matching.sql.RANK_SQL) for one user with 10 chunks, LIMIT 5; random unit vectors. "
                    "ARCHITECTURE.md's local target (matches p95 < 2 s at 1,000 jobs) is for the whole HTTP request; this measures only the query.",
            "postgres_version": pg_version, "pgvector_version": vec_version, "rows": rows}


SCENARIOS = {"matching-scale": scenario_matching_scale, "matching-concurrency": scenario_matching_concurrency,
             "embedding-throughput": scenario_embedding_throughput, "db-ranking-scale": scenario_db_ranking_scale}


def to_markdown(run: dict) -> str:
    L = [f"# Load / scalability measurements ({run['date']})", "",
         "Generated by `python tests/load/run.py`. All figures are measured on the machine below; synthetic random vectors only.",
         "These are component measurements (matching computation and ranking query), **not** an HTTP/API load test and not cloud capacity evidence.", "",
         f"Code version: git `{run['git']['commit'][:10]}`" + (" (uncommitted changes present)" if run["git"]["dirty_outside_evidence"] else "") + ".", "",
         "```json", json.dumps(run["machine"], indent=2), "```", ""]
    for name, res in run["scenarios"].items():
        L += [f"## {name}", "", res.get("note", ""), ""]
        for k in ("postgres_version", "pgvector_version", "model_load_s", "first_call_after_load_ms", "rss_before_load_mb", "rss_after_load_and_use_mb"):
            if k in res:
                L.append(f"- {k}: {res[k]}")
        if "single_text_latency" in res:
            L.append(f"- single text latency: {res['single_text_latency']}")
        rows = res["rows"]
        cols = list(rows[0])
        L += ["", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        L += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
        L.append("")
    return "\n".join(L) + "\n"


API_SCENARIOS = {"api-concurrency": ["api-concurrency"], "browse-during-processing": ["browse-during-processing"],
                 "api": ["api-concurrency", "browse-during-processing"]}


def write_outputs(out_dir: Path, stem: str, record: dict, markdown: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {out_dir / (stem + '.md')}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    ap.add_argument("--scenario", required=True, choices=[*SCENARIOS, "all", *API_SCENARIOS])
    ap.add_argument("--quick", action="store_true", help="smaller grid and fewer repetitions")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--target", help="HTTP scenarios: 'harness' or the base URL of a running API (default: $LOAD_BASE_URL)")
    ap.add_argument("--cookie", help="HTTP scenarios, external API: session cookie as NAME=VALUE from a test login")
    ap.add_argument("--csrf-token", help="HTTP scenarios, external API: X-CSRF-Token value")
    ap.add_argument("--origin", help="HTTP scenarios, external API: Origin header value")
    ap.add_argument("--pdf", type=Path, default=None, help="PDF to upload (default: tests/fixtures/pdf/resume_P10.pdf)")
    ap.add_argument("--deadline", type=float, default=60.0, help="harness child deadline in seconds (default 60)")
    args = ap.parse_args()

    if args.scenario in API_SCENARIOS:
        import api_load
        target = args.target or os.environ.get("LOAD_BASE_URL")
        if not target:
            print("NOT RUN: no API target. Pass --target harness (reference harness, not the project's API) or --target <base URL> "
                  "of a running API with the contract endpoints. No numbers were produced.", file=sys.stderr)
            return 3
        try:
            res = api_load.run_api_scenarios(API_SCENARIOS[args.scenario], target=target, pdf_path=args.pdf or api_load.DEFAULT_PDF,
                                             quick=args.quick, cookie=args.cookie, csrf=args.csrf_token, origin=args.origin,
                                             deadline_s=args.deadline)
        except api_load.NotRun as exc:
            print(f"NOT RUN: {exc}. No numbers were produced.", file=sys.stderr)
            return 3
        meta = {"date": dt.date.today().isoformat(), "machine": machine(), "git": git_state()}
        record = {**meta, **res}
        md = api_load.to_markdown(res, meta)
        print(md)
        if args.out_dir:
            kind = "harness" if res["target"]["kind"] == "harness" else "external"
            write_outputs(args.out_dir, f"load-api-{kind}-{meta['date']}-{args.scenario}" + ("-quick" if args.quick else ""), record, md)
        return 0

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    run = {"date": dt.date.today().isoformat(), "machine": machine(), "git": git_state(), "seed": SEED, "quick": args.quick, "scenarios": {}}
    for name in names:
        print(f"[{name}]", flush=True)
        run["scenarios"][name] = SCENARIOS[name](args.quick)
    if args.out_dir:
        stem = f"load-matching-{run['date']}" + ("" if args.scenario == "all" else f"-{args.scenario}") + ("-quick" if args.quick else "")
        write_outputs(args.out_dir, stem, run, to_markdown(run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
