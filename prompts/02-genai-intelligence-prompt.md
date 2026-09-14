# Prompt 02 — ML/GenAI intelligence layer

> Read `../CLAUDE.md` in full first. Depends on prompt 01 — this reads
> from the silver tables it produced.

---

Build the intelligence layer: the thing that turns a raw assay
reading into a flagged-or-not decision.

Build:

- A UC function `check_toxicity_flag(compound_id, reading_value,
  reading_unit)` that compares a new reading against
  `tox_reference` and `assay_results` history for that compound, and
  returns a structured result — not just true/false, but what it was
  compared against and the margin, since the reviewer downstream
  needs to see the reasoning, not just a flag.
- Decide deliberately between a deterministic threshold rule and an
  LLM call (e.g. via `ai_query` against a Databricks-hosted model) for
  the actual comparison logic, and say which you picked and why in a
  comment — a threshold rule is more auditable and defensible for a
  GxP-adjacent story; an LLM call is a stronger "GenAI" demonstration
  for the submission if you want that framing instead. Either is
  legitimate; don't do both half-heartedly.
- A batch job applying this function across all current
  `assay_results` rows and writing the output to a new silver table,
  `assay_flags` (compound_id, reading_id, is_flagged, reason,
  evaluated_ts).
- Unit tests against a handful of synthetic readings you construct by
  hand: one clearly below threshold, one clearly above, one right at
  the boundary.
- Confirm this ran for real: run the batch job, then run a `SELECT`
  against `assay_flags` showing at least one real flagged and one
  real unflagged row, and commit that actual output as text.

Don't build the Lakebase serving layer yet — that's the next prompt,
and it reads from `assay_flags` here.
