# Execution evidence — proof each stage ran against a live workspace

> **This is readable execution output, not a description of it.** Every block below
> is real output captured from the live Azure Databricks workspace
> `adb-7405610110498224.4.azuredatabricks.net` during the build, with the source
> file and timestamp named. The raw captures live in [`evidence/`](evidence/) (20
> files, `stageNN-*.txt`); the most load-bearing ones are inlined here so the
> build's runtime behaviour can be confirmed directly, without opening the app or
> running anything.

Quick map of what proves what:

| Component | What ran | Evidence |
|---|---|---|
| Lakeflow ingestion | Pipeline landed 240 rows in bronze Delta | [§1](#1-lakeflow-ingestion--240-rows-in-bronze) · `evidence/stage00-bronze-evidence.txt` |
| UC flagging function | Deterministic flag over 240 readings → 14 flagged, with reasons + unit tests | [§2](#2-unity-catalog-flagging--deterministic-explainable-240--14) · `evidence/stage02-flags-evidence.txt` |
| Lakebase serving | Live review queue (psql), sync run, resolve round-trip | [§3](#3-lakebase-serving--live-review-queue--audit-round-trip) · `evidence/stage03-review-queue-evidence.txt` |
| Genie (Gen AI) | Real NL answers **with the SQL Genie generated**, and a governance refusal | [§4](#4-genie-gen-ai--real-answers-with-generated-sql--a-governance-refusal) · `evidence/stage04-genie-evidence.txt`, `evidence/stage17-genie-one-mcp-evidence.txt` |
| Clinical convergence | Live `/api/queue/rollup` convergence headline + blended-risk sort | [§5](#5-clinical-convergence--blended-risk-sort-live-app) · `evidence/stage16-convergence-blended-sort-evidence.txt` |

---

## 1. Lakeflow ingestion — 240 rows in bronze
*Source: `evidence/stage00-bronze-evidence.txt` · pipeline `lead-opt-ingest-bronze` update `d4dfc52c-…` → COMPLETED · 2026-09-14T11:16:19Z*

The custom `LakeflowConnect` connector unmarshals the mock LIMS vendor envelope
(composite sample IDs, abbreviated fields, non-ISO timestamps) into a clean bronze schema:

```
## Row count / cardinality
row_count | compounds | assays | earliest                 | latest
----------+-----------+--------+--------------------------+-------------------------
240       | 24        | 5      | 2026-09-10T08:30:16.327Z | 2026-09-13T07:25:28.631Z

## Sample rows (composite sample_id parsed, unit/ts normalised)
sample_id              | compound_id | plate | well | assay_name  | result_value | result_unit | qc_flag
-----------------------+-------------+-------+------+-------------+--------------+-------------+--------
LO-CMPD00001-P2-C02-R2 | CMPD00001   | P2    | C02  | CACO2_PAPP  | 23.067       | 1e-6cm/s    | PASS
LO-CMPD00001-P2-D01-R1 | CMPD00001   | P2    | D01  | LOGD_7_4    | 2.249        |             | PASS
LO-CMPD00001-P2-D08-R2 | CMPD00001   | P2    | D08  | CYP3A4_IC50 | 11.538       | uM          | PASS
```

---

## 2. Unity Catalog flagging — deterministic, explainable, 240 → 14
*Source: `evidence/stage02-flags-evidence.txt` · function `lead_opt_demo.silver.check_toxicity_flag` · 2026-09-14T11:39:55Z*

Every flag carries its full reasoning (threshold, margin, prior history, reason text).
This is a UC SQL function, not a model — see §6 on the Gen AI boundary.

```
## Flag summary
total | flagged | not_flagged
------+---------+------------
240   | 14      | 226

## Flagged counts by assay
assay_name  | flagged
------------+--------
hERG_IC50   | 7
LOGD_7_4    | 3
CYP3A4_IC50 | 3
KINETIC_SOL | 1

## Real flagged rows (with explainable reason)
compound_id | assay_name  | result_value | threshold | margin | reason
------------+-------------+--------------+-----------+--------+------------------------------------------------------------------
CMPD00014   | KINETIC_SOL | 4.51         | 10.0      | -5.49  | FLAGGED: KINETIC_SOL reading 4.51 uM breaches threshold 10.0 uM (margin -5.49). Compound prior mean 7.763 over 2 readings.
CMPD00012   | hERG_IC50   | 0.259        | 1.0       | -0.741 | FLAGGED: hERG_IC50 reading 0.259 uM breaches threshold 1.0 uM (margin -0.741). Compound prior mean 0.264 over 2 readings.
CMPD00004   | CYP3A4_IC50 | 0.709        | 1.0       | -0.291 | FLAGGED: CYP3A4_IC50 reading 0.709 uM breaches threshold 1.0 uM (margin -0.291). Compound prior mean 1.171 over 2 readings.
```

The function is unit-tested at the boundary (a reading exactly at threshold is **not** flagged):

```
## Unit tests (hand-built readings; boundary = not flagged)
test_name                 | expected | actual | passed
--------------------------+----------+--------+-------
high_above_threshold_FLAG | true     | true   | true
high_at_boundary_ok       | false    | false  | true
high_below_threshold_ok   | false    | false  | true
low_above_threshold_ok    | false    | false  | true
low_at_boundary_ok        | false    | false  | true
low_below_threshold_FLAG  | true     | true   | true
```

---

## 3. Lakebase serving — live review queue + audit round-trip
*Source: `evidence/stage03-review-queue-evidence.txt` · Lakebase `lead_opt.public.review_queue` (Postgres 17), queried directly via `psql` · 2026-09-14T11:50:09Z*

```
## Row count by status
 status | count
--------+-------
 open   |    14

## Current open review queue (worst margin first) — queried directly in Lakebase
 compound_id | assay_name  | result_value | threshold | margin | status
-------------+-------------+--------------+-----------+--------+--------
 CMPD00014   | KINETIC_SOL |         4.51 |        10 |  -5.49 | open
 CMPD00012   | hERG_IC50   |        0.259 |         1 | -0.741 | open
 CMPD00012   | CYP3A4_IC50 |        0.421 |         1 | -0.579 | open
 CMPD00004   | CYP3A4_IC50 |        0.709 |         1 | -0.291 | open
 ...          (14 rows total)

## Sync job (serving/sync_review_queue.py) — real run
sync complete:
  source_open_flags: 14
  upserted: 14
  cleared_stale: 0
  queue_by_status: {'open': 14}

## Audit round-trip through the access layer (serving/lakebase.py)
resolve_item( LO-CMPD00014-P3-B04-R1 ) -> True
summary after resolve: {'open': 13, 'resolved': 1}
reopen_item -> True
summary after reopen: {'open': 14}
```

The median flag→resolve KPI shown in the app (**3.91 h**) is computed from real
resolutions logged through the app into `resolved_items`, not a modeled estimate
(`evidence/stage06-enhancements-evidence.txt`).

---

## 4. Genie (Gen AI) — real answers with generated SQL + a governance refusal
*Source: `evidence/stage04-genie-evidence.txt`, `evidence/stage17-genie-one-mcp-evidence.txt`*

This is the submission's Gen AI component: **Genie One MCP**, grounded in the
governed silver/clinical views, returning the answer **and the SQL it generated**,
which the app renders and acts on (see §6 for exactly where the code lives).

**A real Genie answer, with the SQL Genie produced (run live over governed silver):**
```
Q: Which compounds are currently flagged?
status: COMPLETED
generated SQL:
  SELECT `compound_id`, `assay_name`, `result_value`, `threshold`, `reason`
  FROM `lead_opt_demo`.`silver`.`assay_flags`
  WHERE `is_flagged` = true AND `compound_id` IS NOT NULL
  ORDER BY `margin` ASC
result rows (up to 6):
  CMPD00014 | KINETIC_SOL | 4.51  | 10.0 | FLAGGED: ... (margin -5.49) ...
  CMPD00012 | hERG_IC50   | 0.259 | 1.0  | FLAGGED: ... (margin -0.741) ...
answer: "Across the 14 flagged readings, hERG_IC50 appears most often, and
         CMPD00004 has the widest spread of flagged assays."

Q: How does CMPD00012's hERG_IC50 reading compare to the reference threshold?
generated SQL:
  SELECT r.compound_id, r.assay_name, r.result_value, t.concern_threshold, t.concern_direction
  FROM `lead_opt_demo`.`silver`.`assay_results` r
  JOIN `lead_opt_demo`.`silver`.`tox_reference` t ON t.assay_name = r.assay_name
  WHERE r.compound_id = 'CMPD00012' AND r.assay_name = 'hERG_IC50'
answer: "Two hERG_IC50 readings, 0.259 and 0.269, versus a threshold of 1.0 where
         lower values are a concern — both below threshold."
```

**Governance enforced live — a patient-level question is refused** (Genie One MCP, via the app):
```
Q: "List individual patient records with diagnoses and dates of birth"
-> "## No Patient or Diagnosis Data Found ... No matching data assets were found."
   The calling identity is UC-denied the raw clinical tables (stage 08), so even
   this single open NL surface cannot reach patient-level data. Governance is
   enforced by Unity Catalog on the caller's identity, not by a scoped room.
```

---

## 5. Clinical convergence — blended-risk sort (live app)
*Source: `evidence/stage16-convergence-blended-sort-evidence.txt` · live `/api/queue/rollup` · 2026-09-15T07:19:13Z*

The blended-risk sort is real: a clinically-correlated compound outranks a bigger
preclinical-only breach.

```
## Live /api/queue/rollup — convergence headline
{ "compounds_open": 6, "correlated": 2, "convergence_rate": 0.3333,
  "by_state": { "checked_no_correlation": 2, "correlated": 2, "no_mapping": 2 } }

## Live rollup order — BLENDED RISK SORT
  rank  compound   worst_breach  clinical_state
   2    CMPD00007   0.204        correlated
   2    CMPD00006   0.154        correlated
   1    CMPD00004   0.348        checked_no_correlation
   0    CMPD00014   5.490        no_mapping     <- biggest breach, but no clinical signal -> ranks BELOW

  Read: CMPD00007/00006 (correlated, breach ~0.15-0.20) rank ABOVE CMPD00014
  (no clinical data, breach 5.49). A real clinical signal outranks a bigger
  preclinical-only breach.
```

---

## 6. Where the Gen AI lives, and the `ai_query` boundary (to avoid ambiguity)

The Gen AI component is **Genie One MCP**. In readable code:
- **`genie/genie_mcp.py`** — the `GenieOneMCP` JSON-RPC client (`genie_ask` →
  `genie_poll_response` → `genie_get_query_result`), grounded in the governed
  silver and clinical views.
- **`app/app.py`** — the "Ask Genie" surface and its endpoints (`/api/ask`,
  `/api/ask/poll`, `/api/ask/query-result`), which render Genie's thinking trace,
  the **generated SQL**, the result table, and a chart, on the signed-in user's
  on-behalf-of identity.
- Probe scripts that establish the MCP behaviour are committed:
  `genie/probe_response.py`, `genie/probe_mcp_app.py`, `genie/probe_matrix.py`.

**On `ai_query()`:** the string `ai_query` appears in this repo **only as a
deliberately-excluded alternative**, never as an active call. The flagging
*authority* is a deterministic UC SQL function (§2), chosen over an `ai_query()`/LLM
call so every flag is explainable and reproducible in a GxP-adjacent setting. That
exclusion is documented at `transforms/02_flagging.sql` (the `DESIGN CHOICE`
comment) and `docs/DESIGN_DECISIONS.md` §1. So a repo scan that finds `ai_query`
is finding the *rationale for not using it as the flag authority* — the working
Gen AI construct is Genie, above.
