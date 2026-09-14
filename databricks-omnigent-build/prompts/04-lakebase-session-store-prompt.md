# Prompt 04 — Lakebase session store

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Doesn't depend on prompts 01–03 — can be built in parallel. Paste
this as the matching Omnigent agent from `../agents/`, in the same
project.

---

Build the Lakebase schema and access layer for in-flight sessions and
events — the piece that makes mobile-to-web continuity work, per
the shared context (`../context/00-shared-context.md`).

Build:
- Tables (Postgres-compatible, since Lakebase is Postgres-compatible)
  mirroring the Android side's local model: `sessions`,
  `scan_events`, `observation_events` — same core fields as the
  Android Room entities (`device_id`, `operator_id`, `session_id`,
  `sample_id`, `capture_ts`, `sync_ts`, `source_flag`,
  `correction_of_event_id`), since these rows are what
  `08-api-contract.md`'s sync endpoint writes.
- An access layer (Python, since this will be called from the sync
  API and the agent) with clear read/write functions: write a batch of
  events, read the current session state, mark a session/record
  approved. Don't expose raw SQL to callers outside this layer.
- Indexing appropriate for the two access patterns that matter: fast
  lookup by `session_id` (web client resuming) and fast lookup by
  `sample_id` (agent checking prior events for a compound in-session).
- A migration/setup script so this schema can be stood up
  repeatably, not created by hand once.
- Unit tests against a local or test Lakebase instance for the core
  read/write functions, including the "two clients read the same
  session and see the same state" scenario explicitly, since that's
  the actual continuity guarantee this component exists to provide.

Don't wire this into the sync API or the agent yet — those are
prompts 06 and 05 respectively, and both will import this access
layer rather than talking to Lakebase directly.
