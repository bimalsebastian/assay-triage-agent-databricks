#!/usr/bin/env python3
"""Run a SQL statement against the lead-opt-demo warehouse and print results.

Usage:
  python scripts/dbsql.py "SELECT * FROM lead_opt_demo.bronze.assay_results_raw LIMIT 5"
  echo "CREATE CATALOG ..." | python scripts/dbsql.py -

Uses the Databricks CLI profile + warehouse baked in below. Prints a compact
text table so output can be committed as execution evidence.
"""
import json
import subprocess
import sys
import time

PROFILE = "adb-7405610110498224"
WAREHOUSE_ID = "13d08bfefc608fe6"


def run(sql: str) -> dict:
    payload = {
        "warehouse_id": WAREHOUSE_ID,
        "statement": sql,
        "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE",
    }
    p = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements",
         "-p", PROFILE, "--json", json.dumps(payload)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        sys.exit(p.returncode)
    resp = json.loads(p.stdout)
    stmt_id = resp["statement_id"]
    # poll until finished
    while resp["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        g = subprocess.run(
            ["databricks", "api", "get",
             f"/api/2.0/sql/statements/{stmt_id}", "-p", PROFILE],
            capture_output=True, text=True,
        )
        resp = json.loads(g.stdout)
    return resp


def _print_result(resp):
    state = resp["status"]["state"]
    if state != "SUCCEEDED":
        print(f"STATE: {state}")
        print(json.dumps(resp.get("status", {}), indent=2))
        sys.exit(2)
    result = resp.get("result", {})
    manifest = resp.get("manifest", {})
    cols = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]
    rows = result.get("data_array", [])
    if not cols:
        print(f"OK ({state}) — no result set")
        return
    widths = [len(c) for c in cols]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(str(v)))

    def fmt(vals):
        return " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(vals))

    print(fmt(cols))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt(["NULL" if v is None else v for v in r]))
    print(f"\n({len(rows)} rows)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    # --file runs a semicolon-separated .sql script, statement by statement.
    if sys.argv[1] == "--file":
        with open(sys.argv[2]) as fh:
            text = fh.read()
        # Drop full-line comments first so a leading "-- ..." line doesn't hide
        # the statement, and split on ";" (keep ";" out of string literals).
        code = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("--")
        )
        statements = [s.strip() for s in code.split(";") if s.strip()]
        for i, stmt in enumerate(statements, 1):
            first_line = stmt.splitlines()[0][:80]
            print(f"\n>>> [{i}/{len(statements)}] {first_line}")
            _print_result(run(stmt))
        return
    sql = sys.stdin.read() if sys.argv[1] == "-" else sys.argv[1]
    _print_result(run(sql))


if __name__ == "__main__":
    main()
