# Prompt 08 — clinical Unity Catalog governance

> Read `../CLAUDE.md` in full first. Depends on prompt 07 — reads
> from the bronze table it produced.

---

Govern the clinical bronze data with a visibly stricter posture than
the preclinical side. This prompt is as much about the access-control
decisions as the transform itself — don't treat it as a copy of
prompt 01 with different table names.

Build:

- A transform from `lead_opt_demo_clinical.bronze.ehr_compositions_raw`
  into curated silver tables in the same `lead_opt_demo_clinical`
  catalog: `clinical_observations` (cleaned, typed) and a
  `patient_ref_registry` (distinct synthetic patient references seen
  — no demographic or identifying fields beyond the synthetic
  reference itself).
- A deliberate de-identification/masking step even though the source
  is synthetic: strip or hash any field that would carry real PII in
  a production system (name, DOB, free-text notes) as a matter of
  process, and document in a comment that this step exists because
  the pattern matters even when today's data doesn't require it.
- Grants materially tighter than prompt 01's: read access scoped to
  exactly the service principals that need it (the flagging function
  from prompt 10, the masked Genie view from prompt 12) — no broad
  read grant to the same principals that can read the preclinical
  catalog freely. If you're about to grant the same principal the
  same breadth of access it has on the preclinical catalog, stop and
  reconsider — that's the anti-pattern this prompt exists to avoid.
- A short `GOVERNANCE_NOTES.md` explaining the grant differences
  between this catalog and the preclinical one, for the deck and for
  anyone reviewing the submission.
- Confirm this ran for real: run the transform, query the silver
  tables, and commit the real output as text — plus a real `SHOW
  GRANTS` output for this catalog, since the grants themselves are
  part of what this stage needs to prove.
