# Prompt 10 — extended flagging with clinical correlation

> Read `../CLAUDE.md` in full first. Depends on prompt 02 (existing
> `check_toxicity_flag` / `assay_flags`) and prompt 09 (the
> crosswalk).

---

Extend the existing flagging logic with a second dimension: does a
preclinical flag also correlate with a real-world clinical signal for
the same compound (via its crosswalked drug_code).

Build:

- A new UC function `check_clinical_correlation(compound_id)` that,
  via the crosswalk from prompt 09, looks up the corresponding
  `drug_code` and queries `clinical_observations` for a matching
  signal pattern (for this synthetic build, define "matching" simply
  — e.g. an observation type/value combination you've deliberately
  planted in the synthetic clinical data for at least one compound
  that's also flagged preclinically, so there's a real correlated
  case to demonstrate, not just an always-empty result).
- Extend the `assay_flags` table (or add a companion table,
  `assay_flags_clinical`, if altering the existing schema is riskier
  than adding alongside it — your call, note which you picked and
  why) with a `clinical_correlation` field: null/none if no crosswalk
  mapping exists or no clinical signal found, otherwise a structured
  result showing what was found and in which clinical observation.
- Don't silently treat "no clinical data available for this compound"
  the same as "checked and found no correlation" — these are
  different states and the reviewer needs to be able to tell them
  apart.
- Unit tests: one compound with a real planted correlation, one with
  a crosswalk mapping but no correlated clinical signal, one with no
  crosswalk mapping at all (the ambiguous/missing case from prompt
  09) — three distinct, distinguishable outcomes.
- Confirm this ran for real: run the extended flagging batch, query
  the result showing at least the three distinct outcomes above, and
  commit that real output as text.

Don't build the Lakebase/Genie/app extensions yet — those are the
next three prompts, and they read from what this one produces.
