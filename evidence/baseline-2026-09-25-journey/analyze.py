"""Analyze journey baseline raw results + resource samples into the reported metrics.

    python3 analyze.py > analysis.json     (also prints human tables to stderr)

Reads results_*.json, timeline_*.json and stats_raw.txt from this directory.
"""
import json
import statistics
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
APP = ["inf2006-p1-g6-api-1", "inf2006-p1-g6-db-1", "inf2006-p1-g6-web-1"]


def pctl(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return round(s[0], 1)
    k = (len(s) - 1) * p / 100
    lo = int(k); hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def lat(vals):
    return {"n": len(vals), "p50": pctl(vals, 50), "p95": pctl(vals, 95),
            "max": round(max(vals), 1) if vals else None}


def analyze_scenario(path):
    d = json.loads(path.read_text())
    journeys, wall_total = [], 0.0
    for row in d["rows"]:
        wall_total += row["wall_s"]
        journeys.extend(row["journeys"])
    n = len(journeys)
    completed = [j for j in journeys if j["completed"]]
    # first-attempt success: completed AND no step needed a retry
    first_ok = [j for j in completed if all(s["attempts"] == 1 for s in j["steps"].values())]
    # per-step service latency (final successful attempt ms) and whole-journey duration
    steps = ["prepare", "save", "reload", "matches"]
    step_lat = {}
    for st in steps:
        vals = [j["steps"][st]["ms"] for j in journeys if st in j["steps"] and j["steps"][st]["final_code"] == "OK"]
        step_lat[st] = lat(vals)
    whole = lat([j["whole_ms"] for j in completed])
    # retries / busy / timeouts / errors from trails
    busy = retries = timeouts = 0
    first_busy_save = 0
    http_err, assert_fail = {}, {}
    for j in journeys:
        for st, s in j["steps"].items():
            retries += s["attempts"] - 1
            for code, _ms in s["trail"]:
                if code == "PROCESSING_BUSY":
                    busy += 1
                if code == "PROCESSING_TIMEOUT":
                    timeouts += 1
            if st == "save" and s["first_code"] == "PROCESSING_BUSY":
                first_busy_save += 1
        for e in j["http_errors"]:
            http_err[e] = http_err.get(e, 0) + 1
        for a in j["assert_failures"]:
            assert_fail[a] = assert_fail.get(a, 0) + 1
    return {
        "scenario": d["scenario"], "mode": d["mode"], "clients": d["clients"], "rounds": d["rounds"],
        "journeys": n, "eventual_success": len(completed), "first_attempt_success": len(first_ok),
        "eventual_success_rate": round(len(completed) / n, 3), "first_attempt_rate": round(len(first_ok) / n, 3),
        "wall_s_total": round(wall_total, 2), "completed_per_s": round(len(completed) / wall_total, 3),
        "busy_503_responses": busy, "save_first_attempt_busy": first_busy_save,
        "total_retries": retries, "processing_timeouts": timeouts,
        "http_errors": http_err, "assert_failures": assert_fail,
        "step_latency_ms": step_lat, "whole_journey_ms": whole,
        "browse": browse_stats(d.get("browse", [])),
    }


def browse_stats(browse):
    ms, n, ok = [], 0, 0
    for b in browse:
        n += b["n"]; ok += b["ok"]; ms.extend(b["ms"])
    if n == 0:
        return {"n": 0}
    return {"n": n, "ok": ok, "success_rate": round(ok / n, 4), "latency_ms": lat(ms)}


def parse_stats():
    samples = []  # (epoch, label, name, cpu, mem_mib)
    for line in (DIR / "stats_raw.txt").read_text().splitlines():
        p = line.split()
        if len(p) < 5 or not p[3].endswith("%"):
            continue
        try:
            ep = int(p[0])
        except ValueError:
            continue
        label, name, cpu, mem = p[1], p[2], p[3], p[4]
        v = float(mem[:-3]) if mem.endswith("MiB") else (float(mem[:-3]) * 1024 if mem.endswith("GiB") else None)
        if v is None:
            continue
        samples.append((ep, label, name, float(cpu[:-1]), v))
    return samples


def phase_windows():
    wins = []
    for f in ["timeline_seq.json", "timeline_burst5.json", "timeline_burst10.json"]:
        for e in json.loads((DIR / f).read_text()):
            if e["phase"] != "warmup":
                wins.append(e)
    return wins


def resource_report(samples, wins):
    # sampling cadence: distinct epochs among 'load' samples
    load_eps = sorted({ep for ep, lab, *_ in samples if lab == "load"})
    gaps = [b - a for a, b in zip(load_eps, load_eps[1:])]
    interval = statistics.median(gaps) if gaps else None
    missing = sum(1 for g in gaps if interval and g > 2 * interval)
    # idle
    idle = {}
    for name in APP:
        cpus = [c for ep, lab, nm, c, m in samples if lab == "idle" and nm == name]
        mems = [m for ep, lab, nm, c, m in samples if lab == "idle" and nm == name]
        idle[name] = {"cpu_mean": round(statistics.fmean(cpus), 1) if cpus else None,
                      "cpu_peak": round(max(cpus), 1) if cpus else None,
                      "mem_mib_peak": round(max(mems), 1) if mems else None}
    # idle simultaneous total memory: per-epoch sum
    idle_tot = simultaneous_mem(samples, lambda lab: lab == "idle")
    # per phase
    phases = {}
    for w in wins:
        a, b = w["start_epoch"], w["end_epoch"]
        sub = [(ep, nm, c, m) for ep, lab, nm, c, m in samples if lab == "load" and a <= ep <= b]
        per = {}
        for name in APP:
            cpus = [c for ep, nm, c, m in sub if nm == name]
            mems = [m for ep, nm, c, m in sub if nm == name]
            per[name] = {"cpu_mean": round(statistics.fmean(cpus), 1) if cpus else None,
                         "cpu_peak": round(max(cpus), 1) if cpus else None,
                         "mem_mib_peak": round(max(mems), 1) if mems else None}
        # simultaneous total app memory within this phase (per-epoch sum, then peak)
        tot = simultaneous_mem(samples, lambda lab: lab == "load", a, b)
        phases[w["phase"]] = {"samples": len(sub) // len(APP) if sub else 0, "per_container": per,
                              "simultaneous_app_mem_mib_peak": tot}
    return {"sampling_interval_s_median": interval, "missing_sample_gaps": missing,
            "idle": idle, "idle_simultaneous_app_mem_mib_peak": idle_tot, "phases": phases}


def simultaneous_mem(samples, labpred, a=None, b=None):
    by_ep = {}
    for ep, lab, nm, c, m in samples:
        if not labpred(lab):
            continue
        if a is not None and not (a <= ep <= b):
            continue
        if nm in APP:
            by_ep.setdefault(ep, {})[nm] = m
    peak = None
    for ep, d in by_ep.items():
        if len(d) == len(APP):  # only epochs where all 3 measured -> a true simultaneous reading
            s = sum(d.values())
            peak = s if peak is None or s > peak else peak
    return round(peak, 1) if peak is not None else None


def main():
    out = {"scenarios": {}, "resources": {}}
    for f, key in [("results_seq.json", "sequential"), ("results_burst5.json", "burst5"),
                   ("results_burst10.json", "burst10")]:
        out["scenarios"][key] = analyze_scenario(DIR / f)
    out["resources"] = resource_report(parse_stats(), phase_windows())
    print(json.dumps(out, indent=2))
    # human tables to stderr
    e = sys.stderr
    for key, s in out["scenarios"].items():
        print(f"\n### {key} ({s['mode']} c{s['clients']} x{s['rounds']}rounds) n={s['journeys']}", file=e)
        print(f" eventual={s['eventual_success']}/{s['journeys']} ({s['eventual_success_rate']}) "
              f"first_attempt={s['first_attempt_success']} ({s['first_attempt_rate']}) "
              f"completed/s={s['completed_per_s']}", file=e)
        print(f" busy503={s['busy_503_responses']} save_first_busy={s['save_first_attempt_busy']} "
              f"retries={s['total_retries']} timeouts={s['processing_timeouts']} "
              f"http_errors={s['http_errors']} assert_failures={s['assert_failures']}", file=e)
        for st, l in s["step_latency_ms"].items():
            print(f"   {st:8} p50={l['p50']} p95={l['p95']} max={l['max']} (n={l['n']})", file=e)
        w = s["whole_journey_ms"]
        print(f"   WHOLE    p50={w['p50']} p95={w['p95']} max={w['max']} (n={w['n']})", file=e)
        b = s["browse"]
        if b.get("n"):
            print(f"   browse   n={b['n']} ok_rate={b['success_rate']} p50={b['latency_ms']['p50']} "
                  f"p95={b['latency_ms']['p95']} max={b['latency_ms']['max']}", file=e)
    r = out["resources"]
    print(f"\n### resources: sampling median={r['sampling_interval_s_median']}s missing_gaps={r['missing_sample_gaps']}", file=e)
    print(f" idle simultaneous app mem peak = {r['idle_simultaneous_app_mem_mib_peak']} MiB", file=e)
    for name, v in r["idle"].items():
        print(f"   idle {name}: cpu {v['cpu_mean']}/{v['cpu_peak']} mem_peak {v['mem_mib_peak']}", file=e)
    for ph, v in r["phases"].items():
        print(f" phase {ph} (n={v['samples']}) sim_app_mem_peak={v['simultaneous_app_mem_mib_peak']} MiB", file=e)
        for name, c in v["per_container"].items():
            print(f"   {name}: cpu {c['cpu_mean']}/{c['cpu_peak']} mem_peak {c['mem_mib_peak']}", file=e)


if __name__ == "__main__":
    main()
