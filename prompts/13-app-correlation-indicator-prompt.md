# Prompt 13 — Databricks App correlation indicator

> Read `../CLAUDE.md` in full first. Depends on prompt 11 (extended
> Lakebase queue) and prompt 12 (scoped clinical Genie access). Also
> builds on prompt 06 if you've already done the review-queue
> enhancements — this adds one more field to that same view, it
> doesn't redo it.

---

Surface the clinical correlation signal in the existing dashboard.

Build:

- A correlation indicator on each queue row (or each compound in the
  rollup, if prompt 06's enhancements are in place), rendering the
  three-state distinction from prompt 11 clearly — visually distinct
  treatments for "no clinical data," "checked, no correlation," and
  "correlated signal found." Don't render the first two states the
  same way; a reviewer needs to know whether absence of a correlation
  means "we checked" or "there's nothing to check against."
- Clicking into a correlated item shows the aggregate summary from
  prompt 12's scoped view — not a direct query against clinical
  silver tables from the app itself. The app should go through the
  same scoped surface a Genie question would, not get its own
  backdoor into clinical data.
- If the "ask the Genie room" box from the base build exists, confirm
  a clinical-correlation question asked through it returns a
  sensible answer without needing any app code changes — it should
  just work once prompt 12 is done, since the app was already talking
  to the Genie room generically.
- Confirm this ran for real: render the queue with at least one item
  in each correlation state, and commit the real rendered content
  (the queue's row data including the correlation field, not a
  screenshot) as text — same evidence standard as every prior stage.
