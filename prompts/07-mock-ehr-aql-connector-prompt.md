# Prompt 07 — mock EHR (EHRbase) + AQL Lakeflow connector

> Read `../CLAUDE.md` in full first, especially the "Clinical/openEHR
> extension" section. Independent of prompts 00-06 — this starts a
> parallel track that converges with them at prompt 09.

---

Stand up a mock openEHR Clinical Data Repository and the Lakeflow
connector that ingests from it.

Build:

- **A local EHRbase instance via Docker Compose.** Follow EHRbase's
  own quick-start (it needs a Postgres backend, which the compose
  file typically provisions alongside it). Confirm it's reachable via
  its REST API before building anything on top of it.
- **A small set of archetypes/templates**, kept intentionally narrow:
  something like a lab-result-style archetype and an
  adverse-reaction-style archetype are enough — don't try to model a
  broad clinical dataset. Use EHRbase's template upload endpoint
  (operational template / OPT format) to register them.
- **Synthetic patient compositions**, generated and POSTed into
  EHRbase via its REST API: a handful of synthetic patients, each
  with a few compositions referencing a drug/substance identifier
  that you control (this identifier is what prompt 09's crosswalk
  will map to a compound_id — pick a clean, deliberately simple
  identifier scheme for now, e.g. a synthetic drug code, and note
  that a real integration would need to handle multiple competing
  identifier systems). Keep all patient data clearly synthetic — no
  real names, no real identifiers of any kind.
- **A custom Lakeflow connector** implementing `LakeflowConnect`
  (same interface/pattern as prompt 00's LIMS connector, but the
  read logic here issues AQL queries against EHRbase's REST API
  instead of hitting a flat endpoint) that pulls the compositions and
  flattens them into a clean schema — patient_ref (synthetic, not a
  real identifier), drug_code, observation_type, value, effective_ts.
- A Lakeflow Declarative Pipeline landing this in
  `lead_opt_demo_clinical.bronze.ehr_compositions_raw` — a distinct
  catalog from the preclinical one, per CLAUDE.md's governance note;
  create it now if it doesn't exist.
- Confirm this ran for real: run the pipeline, query the bronze
  table, and commit the real result (row count, sample rows with
  synthetic values only) as text in the repo.

Don't build the governance/silver layer yet — that's the next prompt.
