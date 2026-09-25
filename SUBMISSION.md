# FE Bar Build — submission answers

> This repository is the submission. It is self-contained: the four questions below are
> answered here, and **proof the build ran is in the executed notebook
> [`notebooks/execution_evidence.ipynb`](notebooks/execution_evidence.ipynb)** (committed
> *with its cell outputs visible*; plain-text render:
> [`notebooks/execution_evidence.md`](notebooks/execution_evidence.md)) and in
> [`EVIDENCE.md`](EVIDENCE.md).

### Proof it ran — real output, inline

Captured live from workspace `adb-7405610110498224` (run as `bimal.sebastian@databricks.com`):

```
# Lakeflow ingestion -> bronze Delta:  240 rows | 24 compounds | 5 assays
# Deterministic UC flag function:      240 readings -> 14 flagged (each with its reason)
#                                      hERG_IC50 7 | LOGD_7_4 3 | CYP3A4_IC50 3 | KINETIC_SOL 1
# Genie One MCP (Gen AI), live:        "Which assay has the most flagged readings?" -> "hERG_IC50, 7"
#   generated SQL:  SELECT assay_name, COUNT(*) FROM lead_opt_demo.silver.assay_flags
#                   WHERE is_flagged = true GROUP BY assay_name ORDER BY 2 DESC
# ai_query (Gen AI, advisory+audited): CMPD00012 (correlated) -> "escalate for confirmatory assay"
# Deployed app serving real data:      121 x 200 OK across /api/queue/rollup,/kpi,/flags-by-assay,/ask/poll
```

---

## 1. What is the business challenge you are solving?

In pharma lead optimization, weak compounds get carried through additional synthesis and
assay cycles that should have been avoided, because the early kill signal is scattered and
never surfaces in time to act on it. The signal exists in the data — an off-target or
ADMET reading lands in the LIMS — but acting on it means stitching together LIMS exports,
tox thresholds in spreadsheets, a separate clinical data repository, and BI in PowerBI/Denodo.
A single go/kill decision takes 3–5 days (illustrative), and ~a third to a half of flagged
compounds are carried forward anyway (illustrative), at ~$50K–100K per wasted cycle
(illustrative). And clinical safety data plays almost no role in the early call, because
preclinical and clinical governance are owned by different teams and never converge.

**Who owns these numbers (the accountable buyer):** the **VP / Head of Lead Optimization
(Discovery Sciences)** owns cycle time from flag to kill, cost per wasted cycle, the share
of flagged compounds carried forward, and candidate throughput — and funds the decision.
The **Head of R&D Data & AI Platform / Principal Data Architect** owns governance, per-user
access, data quality, and the audit trail — the approval the funding buyer needs cleared.

## 2. How does your Databricks solution address this challenge?

One governed workspace, end to end, with six integrated stages plus a clinical-convergence
layer (see [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md)):

1. **Lakeflow ingestion** — a custom connector lands raw mock-LIMS readings in bronze Delta.
2. **Governed silver** — Unity Catalog holds curated tox reference, assay results, compound registry, least-privilege grants.
3. **Explainable flagging** — a deterministic UC SQL function (`check_toxicity_flag`) raises every flag with its threshold, margin, prior history, and reason. Not a model.
4. **Operational queue** — Lakebase serves the fast review queue; Delta stays the system of record.
5. **Natural language** — Genie One MCP answers over governed silver and shows the SQL it generated.
6. **Reviewer app** — a Databricks App with the triage queue and a clinical-convergence overlay.

The **clinical layer** fuses the preclinical flag with a clinical adverse-event signal, with
deliberately tighter governance: a separate catalog, de-identification, an aggregate-only
Genie surface, and — see level-ups — explicit UC row-level security + column masks. Every
access is enforced by Unity Catalog; reads and Genie run **on behalf of the signed-in user**
(hybrid OBU), so denial is per-person. Every kill decision is logged with its reasoning.

## 3. What AI tools did you use, what was your workflow, and what trade-offs did you make?

**AI tools:** **Claude Code** as the primary build agent (prompt-per-stage, each stage
committed with real execution evidence); **Genie One MCP** as a runtime Gen AI capability
(NL querying that shows its SQL); an **advisory `ai_query()`** recommendation layer; and
**Stitch** for the UI design.

**Workflow:** research/architecture first, then a stage-by-stage build where each stage ran
against the live workspace and was verified with committed evidence before the next.
See [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md).

**Execution evidence (readable text — the build running live).** The executed notebook
[`notebooks/execution_evidence.ipynb`](notebooks/execution_evidence.ipynb) was run with
`nbconvert --execute` against the live workspace `adb-7405610110498224` as
`bimal.sebastian@databricks.com`; its committed cell outputs include:

```
# Lakeflow ingestion -> bronze (real row counts)
row_count | compounds | assays | earliest                 | latest
240       | 24        | 5      | 2026-09-10T08:30:16.327Z | 2026-09-13T07:25:28.631Z

# Deterministic flagging (240 readings -> 14 flagged), each with its reasoning
total | flagged | not_flagged     hERG_IC50 7 | LOGD_7_4 3 | CYP3A4_IC50 3 | KINETIC_SOL 1
240   | 14      | 226

# Gen AI (1) advisory ai_query() recommendation — REAL model output, logged/audited
CMPD00012 | correlated (2 adverse) | ACTION: escalate for confirmatory assay
                                     RATIONALE: hERG_IC50/CYP3A4_IC50 below threshold, correlated
                                     with qt_prolongation and cardiac_arrhythmia.

# Gen AI (2) Genie One MCP — live NL answer WITH the SQL Genie generated
Q: "Which assay has the most flagged readings?" -> "hERG_IC50, with 7 flagged readings."
generated SQL: SELECT assay_name, COUNT(*) AS flagged_reading_count
               FROM lead_opt_demo.silver.assay_flags WHERE is_flagged = true
               GROUP BY assay_name ORDER BY flagged_reading_count DESC
```

The deployed app returning real data (121 `200 OK`s), the Lakebase queue + sync + audit
round-trip, and a live governance refusal are in [`EVIDENCE.md`](EVIDENCE.md) (23 raw
`evidence/stageNN-*.txt` captures).

**Where the Gen AI lives (both constructs):** **Genie One MCP** — `genie/genie_mcp.py`
(the `GenieOneMCP` client) and the `/api/ask*` endpoints in `app/app.py`; and the advisory
**`ai_query()`** layer — `transforms/18_ai_recommendation.sql`
(`databricks-meta-llama-3-3-70b-instruct`) materialising
`lead_opt_demo.silver.assay_flag_recommendations`, each row logging its input prompt, model
endpoint, and timestamp.

**Decisions and trade-offs:**
- **Deterministic SQL function over an ML/LLM classifier for the flag authority** — GxP-adjacent
  defensibility: every flag reproducible and explainable. `ai_query()` is used only as an
  *advisory* layer downstream, never as the flag authority.
- **Hybrid on-behalf-of-user over a single service principal** — two personas + PHI-shaped
  clinical data, so UC enforces each user's grants; the SP is confined to operational plumbing.
- **Native rendering of Genie over the gated MCP App widget** — the widget is gated/breaks in
  custom app hosts; the app renders Genie's trace + SQL + chart natively instead.
- **Lakebase as serving, not system of record**; **synthetic but PHI-shaped clinical data,
  governed as such**; **native Android deliberately deferred** (can't demo on a Mac; evaluator
  is text-only) while the delivered web UI is genuinely responsive.

## 4. What are the business outcomes and impact?

Killing weak compounds one or more cycles earlier, with a decision that is faster and
defensible. Owned by the **VP / Head of Lead Optimization** (cycle time, cost-per-candidate,
throughput, attrition); the **Head of R&D Data & AI Platform** owns the governance outcomes.

- **Cycle time:** 3–5 days of scattered lookups → under one day on one governed screen (illustrative).
- **Cost avoided:** a framework the customer owns — cost per wasted cycle × cycles saved. Avoiding
  1–2 downstream cycles per deprioritized compound at ~$50K–100K each, across a portfolio, is
  millions/year (illustrative).
- **Higher-conviction kills:** fusing preclinical + clinical signal; illustratively ~10–15% fewer
  late-stage failures.
- **Defensibility:** every decision logged with its reasoning and traceable to a person; Genie
  shows its SQL; clinical data provably separated and scoped — a GxP-adjacent audit posture.

Low-risk to pursue: a 2–3 week Assess phase validates the flagging logic against the customer's
historical decisions before any wider commitment. Illustrative figures are labelled throughout;
the facts (deterministic flag, OBU/UC governance, Genie-shows-SQL, tiered clinical grants, full
audit trail) need no caveat.

---

## Level-ups delivered (each run live, each with evidence)

- **Advisory `ai_query()` action recommendation**, grounded + audited — `transforms/18_ai_recommendation.sql`, `evidence/stage18-ai-recommendation-evidence.txt`.
- **Explicit UC row-level security + column masks on clinical data** — `transforms/19_clinical_rls_masks.sql`, `evidence/stage21-clinical-rls-masks-evidence.txt` (enforcement proven on a non-PI identity).
- **Drift-triggered threshold recalibration** — `serving/drift_recalibration.py`, `evidence/stage22-drift-recalibration-evidence.txt` (hERG_IC50 FPR 50% > 20% opened a review task).
- **Deferred:** instrument-drift / seasonal batch-effect patterns in the synthetic data (a larger data-regeneration effort).
