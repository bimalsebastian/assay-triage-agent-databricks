# Project context

> This file is referenced explicitly by every prompt in `../prompts/`
> (via `../context/00-shared-context.md`). Unlike a `CLAUDE.md` in a
> plain Claude Code session, Omnigent doesn't auto-load it — each
> agent's instructions file points here on purpose, so read this in
> full before starting any stage's task.

## What this build is

The Databricks-side backend and web client for the bench-capture
triage copilot. The Android client (built separately, see the sibling
`android-build-prompts` package) talks only to the sync API this
project exposes — it never calls Genie, UC functions, or the agent
directly. Keep that boundary intact in both directions.

## Components in scope here

- **Lakehouse Delta tables** — curated, governed system of record for
  assay results, compound registry, and toxicology data.
- **UC functions** — governed, callable actions: an ADMET/off-target
  check, and the function that promotes an approved Lakebase record
  into curated Delta tables with lineage tags.
- **Genie space** — natural-language querying over the curated tables,
  exposed to the agent as a tool.
- **Lakebase** — low-latency transactional store for in-flight
  sessions and events, keyed by `session_id` and `sample_id`. This is
  what makes mobile-to-web continuity work: both clients read the same
  session state from here, not from Delta (Delta only gets the
  approved, promoted record).
- **Agent Bricks custom agent** — the orchestrator. Tools: Genie
  space, UC functions, Lakebase read/write. One agent, called by both
  the sync API (on behalf of the Android app) and the web app.
- **Sync API** — the concrete implementation of the contract in
  `08-api-contract.md`. This is the only surface the Android app
  talks to.
- **Databricks App (web)** — the study director's review dashboard,
  and where a scientist can also pick up a session started on the
  handheld.

## Non-negotiables (mirror what the Android side assumes)

- `source_flag` from incoming events (`on_device_heuristic` vs.
  `unflagged`) must pass through untouched to wherever the web UI
  renders it. Never let the agent's own confirmation overwrite or
  relabel the original on-device flag — both should be visible,
  clearly distinguished, in the audit trail.
- `sync_ts` in every sync response is the server's own clock, set at
  the moment the batch is accepted — not copied from any client-
  supplied value.
- Delta promotion only happens after explicit human approval (the
  study director's action in the web app), never automatically on
  sync. Sync writes to Lakebase; approval is what triggers the UC
  function that promotes to Delta.
- Every promoted Delta record carries `device_id`, `operator_id`,
  `capture_ts`, `sync_ts`, and `source_flag` as lineage-tagged columns
  or tags — this is what makes the ALCOA+-style audit trail real
  rather than just claimed.

## Tech stack

Databricks Asset Bundles for deployment, Unity Catalog + Delta Lake,
Genie spaces, Agent Bricks (MLflow-based agent authoring), Lakebase
(Postgres-compatible), Databricks Apps for both the sync API service
and the web dashboard (can be one app or two — decide in prompt 06/07
based on how the framework you're using wants to structure this).

## What "done" looks like for each module

Each numbered prompt is scoped to one component. A component is done
when its tests pass (SQL/data quality checks for tables, unit tests
for UC functions and the sync API, and a manual run-through for the
Genie space and agent) and — critically — when you've re-read
`08-api-contract.md` and confirmed nothing you built silently diverges
from it. If it does, stop and flag it rather than adjusting the
contract unilaterally; the Android builder is relying on it too.
