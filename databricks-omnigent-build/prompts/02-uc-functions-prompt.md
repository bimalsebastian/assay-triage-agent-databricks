# Prompt 02 — UC functions

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Depends on prompt 01. Run this as the matching Omnigent agent from
`../agents/`, in the same project.

---

Build the two governed UC functions described in the shared context, as Python
or SQL UC functions registered in Unity Catalog so they can be called
both by the agent and independently for testing.

Build:
- `check_admet_flag(compound_id, reading_value, reading_unit)` — a
  governed function that runs a quick ADMET/off-target heuristic
  against the toxicology reference table from prompt 01, and returns a
  structured flag result (not just a boolean — include what threshold
  or reference it compared against, since the agent needs to explain
  its reasoning later). Ask me for the actual ADMET logic if it's not
  already specified anywhere in the repo; don't invent scientific
  thresholds yourself.
- `promote_approved_record(lakebase_record_id, approver_id)` — the
  function that takes an approved Lakebase record and writes it into
  the silver assay results table from prompt 01, carrying over
  `device_id`, `operator_id`, `capture_ts`, `sync_ts`, `source_flag`
  unchanged, plus the new `approver_id` and an `approved_ts`. This is
  the only path that writes to the silver table — make sure nothing
  else in this prompt or a later one bypasses it.
- Unit tests for both functions against the seed data from prompt 01,
  including edge cases (no reference data for a compound, a reading
  exactly at a threshold, a record missing a required audit field —
  should fail loudly, not promote with a gap).
- Unity Catalog permission grants so these functions are callable by
  the agent's service principal specifically, not broadly.

Don't wire these into the agent yet — that's prompt 05. This prompt
is about the functions working correctly and being independently
testable.
