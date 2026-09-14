# Project context

## What changed from earlier drafts of this build

This package intentionally drops the Android/mobility angle and the
sync-API/session-continuity design from earlier planning — that
belongs to a different engagement and isn't part of what's being
built or graded here. It also adds a raw-ingestion stage that earlier
drafts skipped straight past. What follows is the actual scope: six
stages, each mapping directly to one required component — Lakeflow,
Unity Catalog, Lakebase, ML/GenAI, Genie, Databricks App — as an
integrated journey, not six siloed demos.

## The problem this solves

In lead optimization, a scientist logging a new assay reading has no
fast way to tell whether it's consistent with what's already known
about that compound family — the data needed to answer that lives
scattered across LIMS exports. Compounds that should be deprioritized
early keep getting carried through additional synthesis and assay
cycles because the signal was there but wasn't surfaced. This build
makes that signal show up immediately, in one place, for both a
scientist asking a question in plain language and a reviewer working
a queue in a dashboard.

## Workspace

Azure Databricks workspace: `https://adb-7405610110498224.4.azuredatabricks.net`

All work happens in a dedicated catalog — use `lead_opt_demo` unless
a prior stage already created something different; don't touch any
other catalog in this workspace. Confirm you're pointed at the right
workspace and profile before creating anything (see the README for
the CLI auth step) — never assume the CLI's default profile is this
workspace.

## The six stages, in build order

1. **Lakeflow** — a mock LIMS service exposing a deliberately
   LIMS-flavored (not clean-JSON) API, plus a custom Lakeflow
   connector that ingests from it into a bronze Delta table. This is
   the raw data entering the system — nothing upstream of this stage
   is hand-seeded.
2. **Unity Catalog** — bronze is transformed into governed, curated
   silver tables (compound registry, assay results, toxicology
   reference), with least-privilege grants. This is governance
   applied to real ingested data, not to hand-written seed rows.
3. **ML or GenAI** — a UC function (or a small registered model,
   your call) that evaluates new assay readings against the tox
   reference data and flags a possible off-target/ADMET concern.
   This is what makes the system "intelligent" — keep the flagging
   logic itself auditable (show what it compared against), not a
   black box.
4. **Lakebase** — a low-latency operational table holding the current
   review queue: compounds with an open flag, ready for a reviewer to
   act on. This is genuinely operational serving, not a copy of the
   Delta table — it's what the app reads for fast, current state
   instead of querying Delta directly for every page load.
5. **Genie Room** — natural-language querying over the curated silver
   tables, so a scientist can ask a plain-language question instead
   of writing SQL or hunting across systems.
6. **Databricks App** — the review dashboard: shows the current queue
   from Lakebase, and gives a reviewer a way to ask the Genie Room a
   follow-up question inline. This is what makes the whole thing
   visible to the business, not just runnable from a notebook.

## Non-negotiables

- Every flagged record carries what it was compared against and why
  — the reviewer-facing story only works if the flag is explainable,
  not just present.
- Stage 4 (Lakebase) is populated *from* the governed silver data and
  the stage-3 flagging output — never write directly to Lakebase from
  raw or ungoverned data, and never let Lakebase become the system of
  record instead of Delta.
- Every stage must produce real execution evidence — actual query
  output, actual run logs, actual records — committed to the repo as
  text, not just working code. A stage isn't done until you've
  committed that evidence.

## Tech stack

Databricks CLI + Python for the mock LIMS service and the custom
Lakeflow connector, Databricks Asset Bundles where useful for
reproducible deployment, Unity Catalog + Delta Lake, a UC function
(SQL/Python) for the flagging logic, Lakebase (Postgres-compatible)
for the review queue, a Genie space over the silver tables, and a
Databricks App for the dashboard.

## What "done" looks like for each stage

A stage is done when it runs against the real workspace above (not a
mock), its output is verifiable by re-running a query or command
yourself, and that real output is committed to the repo. Source code
without a committed run is not done, per the submission's own
evidence requirement.
