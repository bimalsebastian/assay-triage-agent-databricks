# Prompt 06 — sync API

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Depends on prompts 04 and 05. Also needs `08-api-contract.md` in this
folder — read it before writing any endpoint code, and treat it as
fixed unless you stop and flag a needed change (it's shared with the
Android builder). Paste this as the matching Omnigent agent from `../agents/`, in the same
project.

---

Implement the sync API — the only surface the Android app talks to —
as a Databricks App (or a service deployable as one), exposing exactly
the three endpoints in `08-api-contract.md`.

Build:
- `POST /v1/sync` — validates the incoming batch (auth, payload
  shape, `source_flag` is one of the two allowed values), writes
  events to Lakebase via the prompt 04 access layer, triggers the
  agent (prompt 05) asynchronously or synchronously (pick one and note
  why in a comment — synchronous is simpler to reason about for a
  first version, async scales better later), and returns the response
  shape from the contract with server-authoritative `sync_ts`.
- `GET /v1/context-bundle` — reads recent readings and thresholds for
  the requested compound IDs from the silver tables (prompt 01) and
  returns the shape from the contract. Bound the query to the
  requested compound list — never return a full-table dump.
- `GET /v1/session/{session_id}` — reads current session state and
  full event list from Lakebase and returns it in the shape the
  contract defines, including whatever the agent has written back
  (findings, tool call trace) so the web app has everything it needs
  in one call.
- Auth handling matching whatever was resolved in
  `08-api-contract.md`'s open items — if that's still unresolved,
  stop and flag it rather than picking something unilaterally.
- Idempotency handling for `/v1/sync` on retried batches (dedup by
  `event_id`), since the Android side's retry/backoff logic assumes
  this.
- Integration tests hitting these endpoints against a test Lakebase
  and the real agent from prompt 05, including a full round trip:
  sync a batch, fetch the session, confirm what comes back matches
  what was written.
