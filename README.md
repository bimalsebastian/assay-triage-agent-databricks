# Pharma lead-optimization triage — Claude Code build package

Six stages, one per required component (Lakeflow, Unity Catalog,
Lakebase, ML/GenAI, Genie, Databricks App), built as an integrated
journey against your real Azure Databricks workspace.

> **Evaluators: [`SUBMISSION.md`](SUBMISSION.md) answers the four submission questions**,
> and **[`notebooks/execution_evidence.ipynb`](notebooks/execution_evidence.ipynb)** is the
> executed notebook (committed with outputs) that proves the build ran. Both are text-only.

## For evaluators — where to look (all text, no screenshots needed)

- **[`notebooks/execution_evidence.ipynb`](notebooks/execution_evidence.ipynb)** —
  **START HERE. An executed Jupyter notebook, committed WITH its cell outputs visible.**
  It was run with `jupyter nbconvert --execute` against the live workspace
  `adb-7405610110498224` (running as `bimal.sebastian@databricks.com`); every output
  cell is the real result returned at execution time: the ingestion row counts
  (240 rows), the deterministic flagging run (240 → 14 flagged, with each flag's
  reasoning), the clinical convergence counts, the **real `ai_query()` Gen AI model
  output**, and a **live Genie response with the SQL Genie generated**. A plain-text
  rendering of the same run is at
  [`notebooks/execution_evidence.md`](notebooks/execution_evidence.md).
- **[`EVIDENCE.md`](EVIDENCE.md)** — the same proof inlined as readable markdown, plus
  the Lakebase review queue + sync + audit round-trip and a live governance refusal.
- **`evidence/`** — the 21 raw per-stage captures (`stageNN-*.txt`): real query output,
  run logs, and records. Read these, not descriptions of them.
- **`docs/BUILD_PROCESS.md`** — how it was built with Claude Code: the prompt
  sequence, the persistent `CLAUDE.md` contract, and the evidence-gated
  discipline. (Build conversation ID available on request via the submission form.)
- **`docs/DESIGN_DECISIONS.md`** — what was chosen, what was excluded and why, and
  how the solution evolved (incl. the responsive-web-now / native-Android-deferred
  UI surface strategy).
- **`docs/UI_WALKTHROUGH.md`** — a text description of everything the UI renders
  and how each element drives the reviewer's triage decision (since the UI can't
  be seen).
- **`DEPLOY.md`** — operator runbook to reproduce the whole journey in a fresh
  workspace, with a full resource inventory.
- **`connectors/README.md`** — the custom Lakeflow connectors as a reusable
  reference pattern.

## Proof it ran (two blocks; full set in [`EVIDENCE.md`](EVIDENCE.md))

Deterministic flagging over 240 real ingested readings — 14 flagged, each with its
reasoning (`evidence/stage02-flags-evidence.txt`):

```
total | flagged | not_flagged        assay_name  | flagged
------+---------+------------        ------------+--------
240   | 14      | 226                hERG_IC50   | 7
                                     LOGD_7_4    | 3   (+ CYP3A4_IC50 3, KINETIC_SOL 1)
```

A real Genie answer **with the SQL Genie generated**, run live over governed silver
(`evidence/stage04-genie-evidence.txt`):

```
Q: Which compounds are currently flagged?
generated SQL:
  SELECT `compound_id`,`assay_name`,`result_value`,`threshold`,`reason`
  FROM `lead_opt_demo`.`silver`.`assay_flags` WHERE `is_flagged` = true ORDER BY `margin` ASC
answer: "Across the 14 flagged readings, hERG_IC50 appears most often ..."
```

## Who owns these numbers — the accountable buyer

The domain metrics this build targets are not generic. In a real engagement each
is owned by a named, compensated role:

- **VP / Head of Lead Optimization (Discovery Sciences)** — owns and is measured on
  **cycle time from flag to kill decision, cost per wasted synthesis-and-assay
  cycle, the share of flagged compounds carried forward, and candidate throughput.**
  This is the funding buyer; the review-queue KPIs (median flag→resolve, false-positive
  rate, outcome mix) are their operational dashboard.
- **Head of R&D Data & AI Platform / Principal Data Architect (Research Informatics)**
  — owns **governance posture, per-user access enforcement, data quality, PHI-shaped
  clinical security, and the audit trail.** This is the technical approver whose veto
  the funding buyer needs cleared.

The Gen AI shows up in **two** places (see [`EVIDENCE.md` §6-7](EVIDENCE.md#6-where-the-gen-ai-lives-two-constructs-one-clear-boundary)):
**Genie One MCP** for NL querying that shows its SQL (`genie/genie_mcp.py`, the
`/api/ask*` endpoints in `app/app.py`), and an **advisory `ai_query()` recommendation
layer** (`transforms/18_ai_recommendation.sql`) that turns the deterministic flag +
clinical correlation into a logged, auditable "recommended next action". The flag
*authority* stays deterministic — the LLM is advisory and never decides the flag.

## One-time setup

1. Install the Databricks CLI if you haven't already.
2. Authenticate against this specific workspace — don't rely on
   whatever profile happens to be default:

   ```bash
   databricks auth login \
     --host https://adb-7405610110498224.4.azuredatabricks.net \
     --profile lead-opt-demo
   ```

   This opens a browser for a one-time OAuth login, then saves the
   profile to `~/.databrickscfg`.

3. Verify it worked:

   ```bash
   databricks auth profiles
   databricks current-user me --profile lead-opt-demo
   ```

   Both should succeed and show your identity against
   `adb-7405610110498224.4.azuredatabricks.net` before you do
   anything else. If `current-user me` fails, fix that first — every
   later step assumes this works.

4. Set the profile as the default for this project so Claude Code's
   shell commands don't need `--profile` repeated everywhere:

   ```bash
   export DATABRICKS_CONFIG_PROFILE=lead-opt-demo
   ```

   Put this in your shell profile or a project-local `.env` you
   source before starting Claude Code, so it's set for the whole
   session.

5. Confirm you can actually create things in this workspace — quick
   sanity check before committing real build time:

   ```bash
   databricks catalogs list
   databricks unity-catalog schemas list <some-existing-catalog>
   ```

## Running the build

Open Claude Code in this repo's root — it auto-reads `CLAUDE.md`.
Feed the prompts in order, one per sitting:

```
prompts/00-mock-lims-lakeflow-prompt.md
prompts/01-unity-catalog-governance-prompt.md
prompts/02-genai-intelligence-prompt.md
prompts/03-lakebase-serving-prompt.md
prompts/04-genie-room-prompt.md          <- can run in parallel with 03
prompts/05-databricks-app-prompt.md
```

00 → 01 → 02 are strictly sequential. 03 and 04 both depend on 01/02
but not on each other, so you can do them in either order or
interleave them. 05 needs both 03 and 04 done.

For each stage: paste the prompt file's content into Claude Code,
let it work, review what it built, then **commit the code and the
real execution output together** before moving to the next prompt —
per `CLAUDE.md`, a stage isn't done until that evidence is committed.

## Clinical/openEHR extension (prompts 07-13)

Adds clinical data via a mocked openEHR system, converging with the
base build at the crosswalk stage. Run order:

```
prompts/07-mock-ehr-aql-connector-prompt.md      <- independent, can start anytime
prompts/08-clinical-uc-governance-prompt.md      <- depends on 07
prompts/09-compound-drug-crosswalk-prompt.md     <- depends on 01 AND 08 (convergence point)
prompts/10-extended-flagging-prompt.md           <- depends on 02 AND 09
prompts/11-extended-lakebase-queue-prompt.md     <- depends on 03 AND 10
prompts/12-scoped-genie-clinical-prompt.md       <- depends on 04 AND 08
prompts/13-app-correlation-indicator-prompt.md   <- depends on 05, 11, 12 (and 06 if built)
```

07 can be built in parallel with the base build's 00-06 — it's a
separate track until prompt 09. Everything from 09 onward is
sequential. Read `CLAUDE.md`'s "Clinical/openEHR extension" section
before starting 07 — the governance bar changes here, not just the
table names.

## What happened to the earlier Android/Omnigent-flavored package

Superseded. That package was scoped for a different mobility
engagement and was being carried forward out of habit, not because
it belongs in this submission. This package is the one to build from
— it drops Android and the sync-API design entirely, and adds the
Lakeflow raw-ingestion stage (prompt 00) that was missing before.

## Live build KPIs (stage 06)

The review-queue KPI panel shows a **real** number computed from logged
resolutions in Lakebase `resolved_items`, not a modeled estimate:

- **Median time from flag-created to resolved: 3.91 h** (from 3 real
  resolutions logged through the app on 2026-09-14).

This replaces the modeled KPI estimate in the deck — cite the actual
`resolved_items`-derived figure, which grows more representative as more
reviews are logged. See `evidence/stage06-enhancements-evidence.txt`.

### What's next (deferred from stage 06, future-work slide)

- Notifications / alerting on new high-severity flags.
- An SLA / aging view over the open queue.
- An explicit escalation-to-toxicologist action (beyond the
  `escalated_for_confirmatory_assay` resolution reason).
