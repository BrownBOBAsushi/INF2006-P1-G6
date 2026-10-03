"""Run aggregate-only CloudWatch Logs Insights queries (read-only) and save redacted results."""
import json, subprocess, sys, time, datetime, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
OUT = pathlib.Path(sys.argv[1])
GROUP = "/inf2006/inf2006-private-app/web"
end = int(time.time()); start = end - 24 * 3600

QUERIES = {
    "status_by_route": r"""parse @message /^\S+ (?<ts>\S+) "(?<method>[A-Z]+) (?<path>\S+) \S+" (?<status>\d{3}) (?<bytes>\d+)/
| filter ispresent(status)
| stats count(*) as requests by status, method, substr(path, 0, 18) as route_prefix
| sort requests desc
| limit 25""",
    "error_responses_per_hour": r"""parse @message /^\S+ (?<ts>\S+) "(?<method>[A-Z]+) (?<path>\S+) \S+" (?<status>\d{3}) (?<bytes>\d+)/
| filter ispresent(status)
| filter status >= 400
| stats count(*) as error_responses by bin(1h) as hour, status
| sort hour desc
| limit 30""",
}

def aws(*a):
    r = subprocess.run(["aws", *a, "--output", "json"], capture_output=True, text=True)
    if r.returncode: raise SystemExit(r.stderr)
    return json.loads(r.stdout)

body = [f"# CloudWatch Logs Insights — Nginx access log (sanitised format: method, path without query string, status, bytes)",
        f"# Log group: {GROUP}",
        f"# Window (UTC): {datetime.datetime.fromtimestamp(start, datetime.UTC):%Y-%m-%dT%H:%M:%SZ} to {datetime.datetime.fromtimestamp(end, datetime.UTC):%Y-%m-%dT%H:%M:%SZ}",
        "# Read-only: logs start-query / get-query-results. Aggregates only; client IPs are not selected.", ""]
for name, q in QUERIES.items():
    qid = aws("logs", "start-query", "--log-group-name", GROUP, "--start-time", str(start), "--end-time", str(end), "--query-string", q)["queryId"]
    while True:
        res = aws("logs", "get-query-results", "--query-id", qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(2)
    body += [f"## {name}", "Query:", "```", q, "```", f"Status: {res['status']}; records matched: {res.get('statistics', {}).get('recordsMatched')}", ""]
    for row in res.get("results", []):
        body.append("  " + " | ".join(f"{c['field']}={c['value']}" for c in row))
    body.append("")
(OUT / "08-logs-insights.txt").write_text("\n".join(body) + "\n")
print("\n".join(body))
