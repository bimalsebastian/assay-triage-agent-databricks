# Execution evidence — the build running live (readable as text)

This notebook was **executed with `jupyter nbconvert --execute`** against the live Azure
Databricks workspace `adb-7405610110498224`. Every output cell below is the **real result**
returned by the workspace at execution time — actual row counts, real flagged rows with
their reasoning, real Gen AI model output, and a live Genie response with the SQL Genie
generated. No screenshots; everything here is text a reviewer can read directly.

It is committed **with its outputs saved**, so the build's runtime behaviour can be confirmed
without running anything.


```python
import os, datetime, requests

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
    print(f"\n[{len(rows)} row(s)]")

print("Executed:", datetime.datetime.utcnow().isoformat() + "Z", "against", HOST)
```

    Executed: 2026-09-25T14:48:00.012408Z against https://adb-7405610110498224.4.azuredatabricks.net



```python
# Prove this is running live, as a real identity
me = requests.get(f"{HOST}/api/2.0/preview/scim/v2/Me", headers=H).json()
print("Running as:", me.get("userName"), "-", me.get("displayName"))
```

    Running as: bimal.sebastian@databricks.com - Bimal Sebastian


## Stage 0 — Lakeflow ingestion: raw LIMS landed in bronze Delta
The custom connector unmarshalled the awkward vendor envelope into a clean bronze table.


```python
show(*run_sql('''SELECT count(*) AS row_count, count(distinct compound_id) AS compounds,
                        count(distinct assay_name) AS assays,
                        min(acquired_ts) AS earliest, max(acquired_ts) AS latest
                 FROM lead_opt_demo.bronze.assay_results_raw'''))
```

    row_count | compounds | assays | earliest                 | latest                  
    ----------+-----------+--------+--------------------------+-------------------------
    240       | 24        | 5      | 2026-09-10T08:30:16.327Z | 2026-09-13T07:25:28.631Z
    
    [1 row(s)]


## Stage 2 — deterministic, explainable flagging (240 readings -> 14 flagged)
The flag AUTHORITY is a deterministic Unity Catalog SQL function (`check_toxicity_flag`),
not a model. Every flag carries its reasoning.


```python
show(*run_sql('''SELECT count(*) AS total,
                        sum(cast(is_flagged AS int)) AS flagged,
                        sum(cast(NOT is_flagged AS int)) AS not_flagged
                 FROM lead_opt_demo.silver.assay_flags'''))
```

    total | flagged | not_flagged
    ------+---------+------------
    240   | 14      | 226        
    
    [1 row(s)]



```python
show(*run_sql('''SELECT assay_name, count(*) AS flagged
                 FROM lead_opt_demo.silver.assay_flags WHERE is_flagged
                 GROUP BY assay_name ORDER BY flagged DESC'''))
```

    assay_name  | flagged
    ------------+--------
    hERG_IC50   | 7      
    LOGD_7_4    | 3      
    CYP3A4_IC50 | 3      
    KINETIC_SOL | 1      
    
    [4 row(s)]



```python
show(*run_sql('''SELECT compound_id, assay_name, result_value, threshold, margin, reason
                 FROM lead_opt_demo.silver.assay_flags WHERE is_flagged
                 ORDER BY margin ASC LIMIT 5'''), maxw=95)
```

    compound_id | assay_name  | result_value | threshold | margin | reason                                                                                         
    ------------+-------------+--------------+-----------+--------+------------------------------------------------------------------------------------------------
    CMPD00014   | KINETIC_SOL | 4.51         | 10.0      | -5.49  | FLAGGED: KINETIC_SOL reading 4.51 uM breaches synthetic low-concern threshold 10.0 uM (margin -
    CMPD00012   | hERG_IC50   | 0.259        | 1.0       | -0.741 | FLAGGED: hERG_IC50 reading 0.259 uM breaches synthetic low-concern threshold 1.0 uM (margin -0.
    CMPD00012   | hERG_IC50   | 0.269        | 1.0       | -0.731 | FLAGGED: hERG_IC50 reading 0.269 uM breaches synthetic low-concern threshold 1.0 uM (margin -0.
    CMPD00012   | CYP3A4_IC50 | 0.421        | 1.0       | -0.579 | FLAGGED: CYP3A4_IC50 reading 0.421 uM breaches synthetic low-concern threshold 1.0 uM (margin -
    CMPD00004   | CYP3A4_IC50 | 0.709        | 1.0       | -0.291 | FLAGGED: CYP3A4_IC50 reading 0.709 uM breaches synthetic low-concern threshold 1.0 uM (margin -
    
    [5 row(s)]


## Clinical convergence — the blended-risk signal (tighter-governed clinical catalog)
Compounds flagged preclinically AND correlated with a clinical adverse-event signal.


```python
show(*run_sql('''SELECT correlation_state, count(*) AS compounds, coalesce(sum(n_adverse_obs),0) AS adverse_obs
                 FROM lead_opt_demo.silver.assay_flags_clinical
                 GROUP BY correlation_state ORDER BY correlation_state'''))
```

    correlation_state      | compounds | adverse_obs
    -----------------------+-----------+------------
    checked_no_correlation | 2         | 0          
    correlated             | 3         | 4          
    no_mapping             | 3         | 0          
    
    [3 row(s)]



```python
show(*run_sql('SELECT * FROM lead_opt_demo.silver.clinical_correlation_summary ORDER BY correlation_state, compound_id'), maxw=80)
```

    compound_id | correlation_state      | n_adverse_obs | signal_summary                                   
    ------------+------------------------+---------------+--------------------------------------------------
    CMPD00004   | checked_no_correlation | 0             | clinical data checked, no adverse_reaction signal
    CMPD00008   | checked_no_correlation | 0             | clinical data checked, no adverse_reaction signal
    CMPD00006   | correlated             | 1             | adverse_reaction signal present in clinical data 
    CMPD00007   | correlated             | 1             | adverse_reaction signal present in clinical data 
    CMPD00012   | correlated             | 2             | adverse_reaction signal present in clinical data 
    CMPD00003   | no_mapping             | 0             | no clinical mapping available for this compound  
    CMPD00014   | no_mapping             | 0             | no clinical mapping available for this compound  
    CMPD00024   | no_mapping             | 0             | no clinical mapping available for this compound  
    
    [8 row(s)]


## Gen AI (1) — advisory `ai_query()` recommendation, grounded + audited
`transforms/18_ai_recommendation.sql` calls `ai_query()` to turn each flagged compound's
already-computed deterministic reasoning + clinical correlation into a recommended action.
It is ADVISORY (the deterministic flag remains the authority) and every row logs its exact
input prompt, model endpoint, and timestamp. First the code, then the **real model output**.


```python
print(open("../transforms/18_ai_recommendation.sql").read()[:1400])
```

    -- Stage 18 — ADVISORY AI recommendation (Gen AI, ai_query) over the deterministic flags
    --
    -- DESIGN CHOICE: this is the FIRST and ONLY use of ai_query()/an LLM in the build,
    -- and it is deliberately ADVISORY. The flagging AUTHORITY remains the deterministic
    -- UC function check_toxicity_flag (transforms/02_flagging.sql) — see DESIGN_DECISIONS.md #1.
    -- Here the LLM only turns already-computed, deterministic facts (the flag reason text +
    -- the clinical correlation state) into a natural-language recommended NEXT ACTION for the
    -- reviewer. It invents no data. Every recommendation is logged with its exact input prompt,
    -- the model endpoint, and a timestamp, so the audit trail now covers AI-generated GUIDANCE
    -- as well as the human resolution decisions already logged in Lakebase.
    --
    -- Grounding: one row per open-flagged compound, joined to its clinical correlation state.
    -- Model: databricks-meta-llama-3-3-70b-instruct (pay-per-token FM API, batch-inference capable).
    
    CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_flag_recommendations AS
    WITH flagged AS (
      SELECT
        compound_id,
        COUNT(*)                                                          AS n_flags,
        array_join(collect_list(concat(assay_name, ' ', cast(round(result_value,3) AS string),
                                        ' vs threshold ', cast(threshold AS string),
                                        ' (ma



```python
show(*run_sql('''SELECT compound_id, n_flags, correlation_state, recommendation
                 FROM lead_opt_demo.silver.assay_flag_recommendations
                 ORDER BY correlation_state, compound_id'''), maxw=115)
```

    compound_id | n_flags | correlation_state      | recommendation                                                                                                     
    ------------+---------+------------------------+--------------------------------------------------------------------------------------------------------------------
    CMPD00004   | 3       | checked_no_correlation | ACTION: monitor next cycle
    RATIONALE: The compound's assay readings for CYP3A4_IC50, hERG_IC50, and LOGD_7_4 have b
    CMPD00008   | 2       | checked_no_correlation | ACTION: escalate for confirmatory assay
    RATIONALE: The compound CMPD00008 has breached both the LOGD_7_4 and hERG_I
    CMPD00006   | 1       | correlated             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound's hERG_IC50 reading of 0.846 uM breaches the synthe
    CMPD00007   | 1       | correlated             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound's CYP3A4_IC50 reading of 0.796 uM breaches the synt
    CMPD00012   | 3       | correlated             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound CMPD00012 has multiple flagged assay readings for h
    CMPD00003   | 1       | no_mapping             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound's LOGD_7_4 reading of 5.332 breaches the synthetic 
    CMPD00014   | 1       | no_mapping             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound's kinetic solubility reading of 4.51 uM, which is b
    CMPD00024   | 2       | no_mapping             | ACTION: escalate for confirmatory assay
    RATIONALE: The compound's hERG_IC50 readings of 0.988 uM and 0.795 uM both 
    
    [8 row(s)]



```python
# One full AUDIT row: the exact grounded prompt + model + timestamp are logged per recommendation
show(*run_sql('''SELECT model_endpoint, cast(generated_ts AS string) AS generated_ts, recommendation_input
                 FROM lead_opt_demo.silver.assay_flag_recommendations
                 WHERE compound_id = 'CMPD00012' '''), maxw=1200)
```

    model_endpoint                         | generated_ts               | recommendation_input                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            
    ---------------------------------------+----------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    databricks-meta-llama-3-3-70b-instruct | 2026-09-25 13:59:33.664936 | You are assisting a pharma lead-optimization reviewer. This recommendation is ADVISORY only; a deterministic rule already made the flag decision — do not contradict it or invent data. Compound CMPD00012 has 3 flagged assay reading(s). Deterministic flag reasoning: FLAGGED: hERG_IC50 reading 0.259 uM breaches synthetic low-concern threshold 1.0 uM (margin -0.741). Compound prior mean 0.264 over 2 historical readings. || FLAGGED: CYP3A4_IC50 reading 0.421 uM breaches synthetic low-concern threshold 1.0 uM (margin -0.579). Compound prior mean 1.7405 over 2 historical readings. || FLAGGED: hERG_IC50 reading 0.269 uM breaches synthetic low-concern threshold 1.0 uM (margin -0.731). Compound prior mean 0.264 over 2 historical readings.. Assay breaches: hERG_IC50 0.259 vs threshold 1.0 (margin -0.741); CYP3A4_IC50 0.421 vs threshold 1.0 (margin -0.579); hERG_IC50 0.269 vs threshold 1.0 (margin -0.731). Clinical correlation state: correlated (2 adverse observation(s): mapped to DRG-0012 — adverse_reaction signal: qt_prolongation, cardiac_arrhythmia). Reply in exactly two lines, no preamble: line 1 "ACTION: " then one of {deprioritize, escalate for confirmatory assay, monitor next cycle, pro
    
    [1 row(s)]


## Gen AI (2) — Genie One MCP: a live NL question, with the SQL Genie generated
Called live via the committed `GenieOneMCP` client (`genie/genie_mcp.py`). Genie runs over
the governed silver and returns the answer AND the SQL it generated (rendered in the app).


```python
import sys, time
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
print("\nGenie answer:\n", (p.get("final_answer") or p.get("text") or "").split("[")[0].strip())
for qi in (p.get("query_items") or []):
    print("\nGenerated SQL:\n", (qi.get("sql") or qi.get("query") or "").strip())
```

    Genie conversation: ddcd2255 response: bf0917d7 (polling, ~60-90s)


    status: completed
    
    Genie answer:
     ## hERG_IC50 Has the Most Flagged Readings
    
    The **hERG_IC50** assay leads with **7 flagged readings**, more than double any other assay.
    
    Generated SQL:
     SELECT
      `assay_name`,
      COUNT(*) AS flagged_reading_count
    FROM `lead_opt_demo`.`silver`.`assay_flags`
    WHERE `is_flagged` = true
    GROUP BY `assay_name`
    ORDER BY flagged_reading_count DESC

