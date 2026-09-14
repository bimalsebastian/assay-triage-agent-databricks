# Governance notes — preclinical vs clinical catalogs

The clinical catalog (`lead_opt_demo_clinical`) is governed with a
**deliberately tighter posture** than the preclinical catalog
(`lead_opt_demo`). openEHR data is PHI-shaped in the real world even when — as
here — the data is fully synthetic, so it does not inherit the preclinical
catalog's access posture. The differences below are the point of stage 08, not
an accident of which principals happened to need access.

## Grant differences

| Dimension | Preclinical `lead_opt_demo.silver` | Clinical `lead_opt_demo_clinical.silver` |
|---|---|---|
| Grant granularity | `SELECT ON SCHEMA` (whole schema) | `SELECT ON TABLE` (per-table only) |
| Who can read | ingest SP **and** app SP | ingest SP **only** |
| App SP (dashboard) | broad schema read | **no direct grant** — reaches clinical data only via the scoped aggregate Genie view (stage 12) |
| De-identification | n/a | patient reference replaced by a salted one-way hash before it enters silver |

## Why

- **No schema-wide read on clinical.** A schema grant would let a principal read
  any table added to the clinical schema later, including tables that might
  carry more sensitive detail. Table-level grants keep access to exactly the
  two tables that exist and were reviewed.
- **The app SP is intentionally excluded.** It can read the preclinical schema
  freely, but giving it the same breadth here is the exact anti-pattern
  CLAUDE.md's clinical non-negotiable warns against. The dashboard surfaces the
  clinical *correlation indicator* through the stage-12 scoped/aggregate Genie
  view — never by reading `clinical_observations` or `patient_ref_registry`.
- **De-identification as process, not because today's data needs it.** The
  synthetic feed has no names/DOBs/MRNs, but silver still pseudonymizes the
  patient reference and carries only non-identifying clinical fields, so the
  masking step is real and reviewable. In production the salt is a secret and
  free-text notes / demographics would be dropped at this boundary.

## Cross-catalog read (stage 09)

The stage-09 crosswalk lives in the preclinical catalog but must read
`drug_code` from `lead_opt_demo_clinical.silver.clinical_observations`. The
ingest SP holds exactly that narrow table-level SELECT (plus preclinical
`compound_registry` read), so the crosswalk build works under least privilege
without granting the clinical catalog any broader access.
