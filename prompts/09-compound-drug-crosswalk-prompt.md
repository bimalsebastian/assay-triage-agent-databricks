# Prompt 09 — compound-drug crosswalk

> Read `../CLAUDE.md` in full first. This is where the two tracks
> converge — depends on prompt 01 (preclinical `compound_registry`)
> and prompt 08 (clinical `patient_ref_registry` /
> `clinical_observations`, which carry the drug_code from prompt 07).

---

Build the join layer that lets a preclinical compound and a clinical
drug reference be treated as the same thing. Real translational-
medicine integrations spend real effort on this identifier
reconciliation problem — treat it as a genuine design decision, not a
trivial lookup table.

Build:

- A crosswalk table, `lead_opt_demo.silver.compound_drug_crosswalk`
  (in the preclinical catalog, since it's the preclinical side doing
  the lookup outward): `compound_id`, `drug_code`, `mapping_source`
  (how this mapping was established — for this build, say so
  explicitly, e.g. "synthetic 1:1 by design"), `confidence` (for a
  real system this wouldn't always be 1:1 or certain — model that
  honestly even in synthetic data by including at least one
  ambiguous or missing mapping case).
- A cross-catalog read: this table needs to read `drug_code` values
  that actually appear in `lead_opt_demo_clinical.silver.clinical_observations`
  and `compound_id` values from `lead_opt_demo.silver.compound_registry`
  — confirm the grants from prompt 08 actually allow this specific,
  narrow read before assuming it works.
- A short note in the table's comment or a companion markdown file
  explaining, for the deck: in a real deployment this crosswalk would
  need to handle multiple identifier systems (INN, product code,
  internal compound ID) and wouldn't be a clean 1:1 mapping — this
  build's version is intentionally simplified and that's stated
  outright, not implied to be solved.
- Confirm this ran for real: run the build, query the crosswalk table
  showing both a clean mapping and the deliberately ambiguous/missing
  case, and commit that real output as text.

Don't build the extended flagging logic yet — that's the next prompt,
and it reads from this crosswalk.
