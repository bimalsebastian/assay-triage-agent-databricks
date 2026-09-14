# Prompt 03 — Lakebase operational serving

> Read `../CLAUDE.md` in full first. Depends on prompt 02 — this
> reads from the `assay_flags` table it produced.

---

Build the operational-serving layer: a fast, current view of what
needs review right now, backed by Lakebase rather than a live query
against Delta on every page load.

Build:

- A Lakebase (Postgres-compatible) table `review_queue`: one row per
  currently-open flagged compound, sourced from `assay_flags` where
  `is_flagged = true` and not yet resolved. Include the reasoning
  fields from prompt 02 so the app doesn't need a second round-trip
  to Delta to show why something's flagged.
- A sync job (can be simple — a scheduled job or a call at the end of
  prompt 02's batch run) that upserts new flags into `review_queue`
  and removes/marks resolved ones once a reviewer acts (the "resolve"
  action itself can be a stub for now — a status column and a
  function to set it — since prompt 05's app is what actually
  triggers it).
- A small Python access layer (read current queue, mark an item
  resolved) that prompt 05's app will import rather than talking to
  Lakebase directly with raw SQL scattered through the app code.
- Confirm this ran for real: run the sync, then query `review_queue`
  directly and commit the actual current contents as text — this is
  the table your dashboard will read from, so it needs to have real
  rows in it before you build the app on top of it.

Don't build the app yet — that's prompt 05, and the Genie Room
(prompt 04) can be built in parallel since it doesn't depend on this
stage.
