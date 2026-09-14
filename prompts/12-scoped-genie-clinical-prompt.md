# Prompt 12 — scoped Genie room for clinical data

> Read `../CLAUDE.md` in full first. Depends on prompt 04 (existing
> Genie room) and prompt 08 (clinical silver tables + grants).

---

Extend natural-language querying to cover clinical correlation
without exposing patient-level detail through an open chat surface.
This is a distinct design decision from prompt 04, not a config
copy-paste — read the non-negotiable in CLAUDE.md's clinical
extension section again before starting.

Build:

- Decide, and document the decision: does the existing Genie room
  from prompt 04 get extended to include an aggregate-only clinical
  view, or does clinical get its own separate, more tightly scoped
  Genie room? Either is defensible; a single unscoped room covering
  both preclinical and raw clinical detail is not.
- An aggregate/masked view — `clinical_correlation_summary` or
  similar — exposing only what's needed for the review workflow
  (compound_id, correlation state, a general description of the
  signal type) with no patient-level fields, no raw
  `clinical_observations` rows, reachable by the Genie room.
- Confirm the Genie room's underlying identity can reach this view
  and cannot reach `clinical_observations` or `patient_ref_registry`
  directly — verify this by attempting a query that would need raw
  clinical detail and confirming it's correctly out of scope, not
  just assuming the grants handle it.
- Update `GENIE_QUESTIONS.md` from prompt 04 with 2-3 new sample
  questions specific to this (e.g. "which flagged compounds have a
  clinical correlation") and their expected resolution.
- Confirm this ran for real: actually ask the Genie room each new
  question and commit the real question/answer pairs as text, plus
  the verification attempt showing the out-of-scope query correctly
  failing or returning nothing.
