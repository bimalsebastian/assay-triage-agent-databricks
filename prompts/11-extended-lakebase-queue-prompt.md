# Prompt 11 — extended Lakebase review queue

> Read `../CLAUDE.md` in full first. Depends on prompt 03 (existing
> `review_queue`) and prompt 10 (the extended flagging output).

---

Add the clinical correlation signal to the existing Lakebase review
queue.

Build:

- A `clinical_correlation` column on the existing `review_queue`
  table (or a joined companion table, matching whatever choice you
  made in prompt 10) — carrying the same three-state distinction from
  prompt 10 (no crosswalk mapping / mapped but no signal / mapped
  with a correlated signal), not collapsed into a boolean.
- Update the sync job from prompt 03 to populate this field from the
  extended flagging output when it upserts into the queue.
- Update the Python access layer from prompt 03 so callers (the app,
  prompt 13) can read this field without needing to know about the
  underlying table structure.
- Confirm this ran for real: run the sync, query `review_queue`
  directly, and commit real output showing at least one row in each
  of the three correlation states — this is what prompt 13's UI will
  need to render distinctly, so it needs to actually exist in the
  data first.
