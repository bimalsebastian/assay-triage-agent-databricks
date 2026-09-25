#!/usr/bin/env python3
"""Builds notebooks/execution_evidence.ipynb. Run, then execute with nbconvert so
the cell OUTPUTS are captured and committed (text-readable execution evidence)."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md("""# Execution evidence — the build running live (readable as text)

This notebook was **executed with `jupyter nbconvert --execute`** against the live Azure
Databricks workspace `adb-7405610110498224`. Every output cell below is the **real result**
returned by the workspace at execution time — actual row counts, real flagged rows with
their reasoning, real Gen AI model output, and a live Genie response with the SQL Genie
generated. No screenshots; everything here is text a reviewer can read directly.

It is committed **with its outputs saved**, so the build's runtime behaviour can be confirmed
without running anything.""")

code("""import os, datetime, requests

HOST = "https://adb-7405610110498224.4.azuredatabricks.net"
WAREHOUSE_ID = "13d08bfefc608fe6"
TOKEN = os.environ["DATABRICKS_TOKEN"]          # OAuth token from the Databricks CLI profile
H = {"Authorization": f"Bearer {TOKEN}"}

def run_sql(stmt, wait="50s"):
    r = requests.post(f"{HOST}/api/2.0/sql/statements", headers=H,
                      json={"warehouse_id": WAREHOUSE_ID, "wait_timeout": wait, "statement": stmt})
    d = r.json()
    st = d.get("status", {}).get("state")
    if st != "SUCCEEDED":
        raise RuntimeError(f"{st}: {d.get('status',{}).get('error',{}).get('message','')}")
    cols = [c["name"] for c in d["manifest"]["schema"]["columns"]]
    rows = d.get("result", {}).get("data_array", []) or []
    return cols, rows

def show(cols, rows, maxw=70):
    widths = [min(maxw, max(len(c), *([len(str(r[i])) if r[i] is not None else 0 for r in rows] or [0]))) for i, c in enumerate(cols)]
    line = lambda vals: " | ".join(str(v if v is not None else "")[:maxw].ljust(widths[i]) for i, v in enumerate(vals))
    print(line(cols)); print("-+-".join("-"*w for w in widths))
    for r in rows: print(line(r))
    print(f"\\n[{len(rows)} row(s)]")

print("Executed:", datetime.datetime.utcnow().isoformat() + "Z", "against", HOST)""")

code("""# Prove this is running live, as a real identity
me = requests.get(f"{HOST}/api/2.0/preview/scim/v2/Me", headers=H).json()
print("Running as:", me.get("userName"), "-", me.get("displayName"))""")

md("""## Stage 0 — Lakeflow ingestion: raw LIMS landed in bronze Delta
The custom connector unmarshalled the awkward vendor envelope into a clean bronze table.""")
code("""show(*run_sql('''SELECT count(*) AS row_count, count(distinct compound_id) AS compounds,
                        count(distinct assay_name) AS assays,
                        min(acquired_ts) AS earliest, max(acquired_ts) AS latest
                 FROM lead_opt_demo.bronze.assay_results_raw'''))""")

md("""## Stage 2 — deterministic, explainable flagging (240 readings -> 14 flagged)
The flag AUTHORITY is a deterministic Unity Catalog SQL function (`check_toxicity_flag`),
not a model. Every flag carries its reasoning.""")
code("""show(*run_sql('''SELECT count(*) AS total,
                        sum(cast(is_flagged AS int)) AS flagged,
                        sum(cast(NOT is_flagged AS int)) AS not_flagged
                 FROM lead_opt_demo.silver.assay_flags'''))""")
code("""show(*run_sql('''SELECT assay_name, count(*) AS flagged
                 FROM lead_opt_demo.silver.assay_flags WHERE is_flagged
                 GROUP BY assay_name ORDER BY flagged DESC'''))""")
code("""show(*run_sql('''SELECT compound_id, assay_name, result_value, threshold, margin, reason
                 FROM lead_opt_demo.silver.assay_flags WHERE is_flagged
                 ORDER BY margin ASC LIMIT 5'''), maxw=95)""")

md("""## Clinical convergence — the blended-risk signal (tighter-governed clinical catalog)
Compounds flagged preclinically AND correlated with a clinical adverse-event signal.""")
code("""show(*run_sql('''SELECT correlation_state, count(*) AS compounds, coalesce(sum(n_adverse_obs),0) AS adverse_obs
                 FROM lead_opt_demo.silver.assay_flags_clinical
                 GROUP BY correlation_state ORDER BY correlation_state'''))""")
code("""show(*run_sql('SELECT * FROM lead_opt_demo.silver.clinical_correlation_summary ORDER BY correlation_state, compound_id'), maxw=80)""")

md("""## Gen AI (1) — advisory `ai_query()` recommendation, grounded + audited
`transforms/18_ai_recommendation.sql` calls `ai_query()` to turn each flagged compound's
already-computed deterministic reasoning + clinical correlation into a recommended action.
It is ADVISORY (the deterministic flag remains the authority) and every row logs its exact
input prompt, model endpoint, and timestamp. First the code, then the **real model output**.""")
code("""print(open("../transforms/18_ai_recommendation.sql").read()[:1400])""")
code("""show(*run_sql('''SELECT compound_id, n_flags, correlation_state, recommendation
                 FROM lead_opt_demo.silver.assay_flag_recommendations
                 ORDER BY correlation_state, compound_id'''), maxw=115)""")
code("""# One full AUDIT row: the exact grounded prompt + model + timestamp are logged per recommendation
show(*run_sql('''SELECT model_endpoint, cast(generated_ts AS string) AS generated_ts, recommendation_input
                 FROM lead_opt_demo.silver.assay_flag_recommendations
                 WHERE compound_id = 'CMPD00012' '''), maxw=1200)""")

md("""## Gen AI (2) — Genie One MCP: a live NL question, with the SQL Genie generated
Called live via the committed `GenieOneMCP` client (`genie/genie_mcp.py`). Genie runs over
the governed silver and returns the answer AND the SQL it generated (rendered in the app).""")
code("""import sys, time
sys.path.insert(0, "../genie")
from genie_mcp import GenieOneMCP

g = GenieOneMCP(HOST, lambda: TOKEN)
s = g.start("Which assay has the most flagged readings?")
cid, rid = s["conversation_id"], s["response_id"]
print("Genie conversation:", cid[:8], "response:", rid[:8], "(polling, ~60-90s)")
for _ in range(45):
    time.sleep(4)
    p = g.poll(cid, rid)
    if g.is_terminal(p.get("status")):
        break
print("status:", p.get("status"))
print("\\nGenie answer:\\n", (p.get("final_answer") or p.get("text") or "").split("[")[0].strip())
for qi in (p.get("query_items") or []):
    print("\\nGenerated SQL:\\n", (qi.get("sql") or qi.get("query") or "").strip())""")

nb["cells"] = cells
nb["metadata"] = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                  "language_info": {"name": "python"}}
nbf.write(nb, "execution_evidence.ipynb")
print("wrote execution_evidence.ipynb with", len(cells), "cells")
