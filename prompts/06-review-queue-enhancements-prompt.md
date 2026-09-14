# Prompt 06 — review queue enhancements

> Read `../CLAUDE.md` in full first. Depends on prompts 03 (Lakebase
> review queue) and 05 (the Databricks App) — this extends both,
> it doesn't replace them.

---

Enhance the existing review queue and app based on a working review
of the current build. The current version is a flat list of
individual flagged readings sorted by insertion order, with a bare
Resolve button. This prompt fixes the structural gaps that showed up
once real data was in it.

Build:

- **Compound-level rollup.** The current queue treats each flagged
  reading as an independent row, which hides the actual signal: a
  compound with three separate flags across different assays is a
  much stronger stop-or-advance signal than any single flagged
  reading. Add a rollup view — one row per compound with an open flag
  count — above or instead of the flat list, with each compound
  expandable to show its individual flagged readings underneath (the
  detail the current view already has, just nested now).
- **Severity-based sorting.** Sort by how far the reading breached its
  threshold (the margin already computed in prompt 02's flagging
  output), not by insertion order — surface the widest-margin
  breaches first within each compound.
- **Resolution reason.** Extend the Lakebase `review_queue` schema (or
  add a companion `resolved_items` table, since a resolved row leaves
  the active queue) with `resolution_reason` (an enum: false_positive,
  confirmed_concern, escalated_for_confirmatory_assay),
  `resolved_by`, and `resolved_ts`. Update the Resolve action in the
  app to require picking a reason before it completes — don't let it
  resolve silently.
- **Compound history on drill-in.** When a reviewer expands a
  compound, show its actual historical readings for that assay (not
  just the "prior mean over N readings" text already there) — a
  simple table or small trend chart is enough, doesn't need to be
  elaborate.
- **Flags-by-assay-type summary.** A small panel (counts, last N
  days) showing how many open flags come from each assay type. This
  is what makes a miscalibrated threshold visible — if one assay type
  is generating most of the flags, that's worth surfacing rather than
  burying in fourteen individual rows.
- **A KPI panel using the resolution data above**: median time from
  flag-created to resolved, computed from real `resolved_items` rows,
  not modeled. Update `README.md` or the deck source to note once you
  have a few real resolutions logged that this can replace the
  modeled KPI estimate with an actual number from the build.

Keep out of scope for now (note these as "what's next" material
rather than building them): notifications/alerting on new
high-severity flags, an SLA/aging view, and an escalation-to-toxicologist
action. These are good for a future-work slide, not needed to
demonstrate the integrated journey.

Confirm this ran for real: after building, actually resolve at least
one item through the app with a picked reason, expand at least one
compound to see its history, and commit the real rendered output
(queue rollup content, the resolution record, the KPI panel's number)
as text in the repo — same evidence standard as every other stage.
