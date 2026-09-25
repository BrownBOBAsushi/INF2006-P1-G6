"""Analyze a v2 run directory into reported metrics.  python3 analyze.py <run_dir> > <run_dir>/analysis.json
Prints human tables to stderr. Separates successful-only latency from failed-journey durations, counts
attempt-budget vs elapsed-deadline exhaustion, and computes simultaneous total app memory (per-timestamp
sum, never a sum of independent peaks)."""
import json
import statistics
import sys
from pathlib import Path

APP = ["inf2006-p1-g6-api-1", "inf2006-p1-g6-db-1", "inf2006-p1-g6-web-1"]


def pctl(v, p):
    if not v:
        return None
    s = sorted(v)
    if len(s) == 1:
        return round(s[0], 1)
    k = (len(s) - 1) * p / 100
    lo = int(k); hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def lat(v):
    return {"n": len(v), "p50": pctl(v, 50), "p95": pctl(v, 95), "max": round(max(v), 1) if v else None}


def analyze_scenario(path):
    d = json.loads(path.read_text())
    journeys, wall = [], 0.0
    for row in d["rows"]:
        wall += row["wall_s"]; journeys.extend(row["journeys"])
    n = len(journeys)
    completed = [j for j in journeys if j["completed"]]
    failed = [j for j in journeys if not j["completed"]]
    first_ok = [j for j in completed if all(s["attempts"] == 1 for s in j["steps"].values())]
    fixture_eval = [j for j in journeys if j.get("fixture_ok") is not None]
    fixture_ok = [j for j in fixture_eval if j["fixture_ok"]]
    steps = ["prepare", "save", "reload", "matches"]
    step_lat = {st: lat([j["steps"][st]["ms"] for j in completed if st in j["steps"] and j["steps"][st]["final_code"] == "OK"])
                for st in steps}
    busy = retries = timeouts = 0
    exhaustion = {"attempt_budget": 0, "elapsed_deadline": 0}
    http_err, assert_fail, fix_fail = {}, {}, {}
    for j in journeys:
        for st, s in j["steps"].items():
            retries += s["attempts"] - 1
            for code, _ in s["trail"]:
                busy += code == "PROCESSING_BUSY"
                timeouts += code == "PROCESSING_TIMEOUT"
            if s.get("exhausted"):
                exhaustion[s["exhausted"]] += 1
        for e in j["http_errors"]:
            http_err[e] = http_err.get(e, 0) + 1
        for a in j["assert_failures"]:
            assert_fail[a] = assert_fail.get(a, 0) + 1
        for a in j["fixture_failures"]:
            fix_fail[a] = fix_fail.get(a, 0) + 1
    return {
        "scenario": d["scenario"], "mode": d["mode"], "clients": d["clients"], "rounds": d["rounds"],
        "journeys": n, "eventual_success": len(completed), "first_attempt_success": len(first_ok),
        "eventual_success_rate": round(len(completed) / n, 3), "first_attempt_rate": round(len(first_ok) / n, 3),
        "fixture_evaluated": len(fixture_eval), "fixture_ok": len(fixture_ok),
        "fixture_ok_rate": round(len(fixture_ok) / len(fixture_eval), 3) if fixture_eval else None,
        "wall_s_total": round(wall, 2), "completed_per_s": round(len(completed) / wall, 3),
        "busy_503_responses": busy, "total_retries": retries, "processing_timeouts": timeouts,
        "exhaustion": exhaustion, "http_errors": http_err, "assert_failures": assert_fail, "fixture_failures": fix_fail,
        "step_latency_ms_successful_only": step_lat,
        "whole_journey_ms_completed": lat([j["whole_ms"] for j in completed]),
        "failed_journey_ms": lat([j["whole_ms"] for j in failed]),
        "browse": browse_stats(d.get("browse", [])),
    }


def browse_stats(browse):
    ms, n, ok, codes = [], 0, 0, {}
    for b in browse:
        n += b["n"]; ok += b["ok"]; ms.extend(b["ms"])
        for c, k in b.get("non_ok_codes", {}).items():
            codes[c] = codes.get(c, 0) + k
    if not n:
        return {"n": 0}
    return {"n": n, "ok": ok, "success_rate": round(ok / n, 4), "non_ok_codes": codes, "latency_ms": lat(ms)}


def parse_stats(run):
    out = []
    for line in (run / "stats_raw.txt").read_text().splitlines():
        p = line.split()
        if len(p) < 5 or not p[3].endswith("%"):
            continue
        try:
            ep = int(p[0])
        except ValueError:
            continue
        mem = p[4]
        v = float(mem[:-3]) if mem.endswith("MiB") else (float(mem[:-3]) * 1024 if mem.endswith("GiB") else None)
        if v is None:
            continue
        out.append((ep, p[1], p[2], float(p[3][:-1]), v))
    return out


def sim_mem(samples, labpred, a=None, b=None):
    by = {}
    for ep, lab, nm, c, m in samples:
        if not labpred(lab) or (a is not None and not (a <= ep <= b)) or nm not in APP:
            continue
        by.setdefault(ep, {})[nm] = m
    peak = None
    for ep, d in by.items():
        if len(d) == len(APP):
            s = sum(d.values()); peak = s if peak is None or s > peak else peak
    return round(peak, 1) if peak is not None else None


def resources(run, samples):
    wins = []
    for f in run.glob("timeline_*.json"):
        for e in json.loads(f.read_text()):
            if e["phase"] != "warmup":
                wins.append(e)
    load_eps = sorted({ep for ep, lab, *_ in samples if lab == "load"})
    gaps = [b - a for a, b in zip(load_eps, load_eps[1:])]
    interval = statistics.median(gaps) if gaps else None
    missing = sum(1 for g in gaps if interval and g > 2 * interval)
    idle = {}
    for nm in APP:
        cs = [c for ep, lab, n2, c, m in samples if lab == "idle" and n2 == nm]
        ms = [m for ep, lab, n2, c, m in samples if lab == "idle" and n2 == nm]
        idle[nm] = {"cpu_mean": round(statistics.fmean(cs), 1) if cs else None,
                    "cpu_peak": round(max(cs), 1) if cs else None, "mem_mib_peak": round(max(ms), 1) if ms else None}
    phases = {}
    for w in sorted(wins, key=lambda x: x["start_epoch"]):
        a, b = w["start_epoch"], w["end_epoch"]
        sub = [(nm, c, m) for ep, lab, nm, c, m in samples if lab == "load" and a <= ep <= b]
        per = {}
        for nm in APP:
            cs = [c for n2, c, m in sub if n2 == nm]; ms = [m for n2, c, m in sub if n2 == nm]
            per[nm] = {"cpu_mean": round(statistics.fmean(cs), 1) if cs else None,
                       "cpu_peak": round(max(cs), 1) if cs else None, "mem_mib_peak": round(max(ms), 1) if ms else None}
        phases[w["phase"]] = {"samples": len(sub) // len(APP) if sub else 0, "per_container": per,
                              "simultaneous_app_mem_mib_peak": sim_mem(samples, lambda l: l == "load", a, b)}
    return {"sampling_interval_s_median": interval, "missing_sample_gaps": missing, "idle": idle,
            "idle_simultaneous_app_mem_mib_peak": sim_mem(samples, lambda l: l == "idle"), "phases": phases}


def main():
    run = Path(sys.argv[1])
    out = {"run_dir": str(run), "scenarios": {}, "resources": {}}
    for f, k in [("results_seq.json", "sequential"), ("results_burst5.json", "burst5"), ("results_burst10.json", "burst10")]:
        if (run / f).exists():
            out["scenarios"][k] = analyze_scenario(run / f)
    out["resources"] = resources(run, parse_stats(run))
    print(json.dumps(out, indent=2))
    e = sys.stderr
    for k, s in out["scenarios"].items():
        print(f"\n### {k} n={s['journeys']} eventual={s['eventual_success']} first={s['first_attempt_success']} "
              f"fixture_ok={s['fixture_ok']}/{s['fixture_evaluated']} completed/s={s['completed_per_s']}", file=e)
        print(f"  busy={s['busy_503_responses']} retries={s['total_retries']} timeouts={s['processing_timeouts']} "
              f"exhaustion={s['exhaustion']} http_errors={s['http_errors']} asserts={s['assert_failures']} fixture_fail={s['fixture_failures']}", file=e)
        for st, l in s["step_latency_ms_successful_only"].items():
            print(f"   {st:8} p50={l['p50']} p95={l['p95']} max={l['max']} n={l['n']}", file=e)
        w, fj = s["whole_journey_ms_completed"], s["failed_journey_ms"]
        print(f"   WHOLE(ok) p50={w['p50']} p95={w['p95']} max={w['max']} n={w['n']}  FAILED-dur p50={fj['p50']} max={fj['max']} n={fj['n']}", file=e)
        b = s["browse"]
        if b.get("n"):
            print(f"   browse n={b['n']} ok_rate={b['success_rate']} p50={b['latency_ms']['p50']} p95={b['latency_ms']['p95']} codes={b['non_ok_codes']}", file=e)
    r = out["resources"]
    print(f"\n### resources sampling_median={r['sampling_interval_s_median']}s missing={r['missing_sample_gaps']} "
          f"idle_sim_mem={r['idle_simultaneous_app_mem_mib_peak']}MiB", file=e)
    for nm, v in r["idle"].items():
        print(f"   idle {nm}: cpu {v['cpu_mean']}/{v['cpu_peak']} mem {v['mem_mib_peak']}", file=e)
    for ph, v in r["phases"].items():
        print(f" {ph} n={v['samples']} sim_mem={v['simultaneous_app_mem_mib_peak']}MiB "
              f"api_cpu={v['per_container'][APP[0]]['cpu_mean']}/{v['per_container'][APP[0]]['cpu_peak']}", file=e)


if __name__ == "__main__":
    main()
