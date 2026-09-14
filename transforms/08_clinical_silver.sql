-- Stage 08 — clinical Unity Catalog governance (deliberately STRICTER than 01).
-- Curates the clinical bronze into silver, with a de-identification step and
-- grants that are visibly tighter than the preclinical catalog's (see
-- GOVERNANCE_NOTES.md). This is as much about the access decisions as the SQL.

CREATE SCHEMA IF NOT EXISTS lead_opt_demo_clinical.silver
  COMMENT 'Curated clinical observations (stage 08) — PHI-shaped posture';

-- De-identification / masking step.
-- The source is synthetic and carries no real PII, but this step exists as a
-- matter of PROCESS because the pattern is what matters: in production the raw
-- feed would carry names, DOBs, MRNs and free-text notes. Here we (a) replace
-- the (already synthetic) patient reference with a salted one-way hash so no
-- upstream identifier flows into silver, and (b) would drop any name/DOB/notes
-- columns — none exist in this synthetic feed, but the projection below is
-- explicit about carrying ONLY the non-identifying clinical fields. The salt
-- would be a secret in production, not an inline literal.
CREATE OR REPLACE TABLE lead_opt_demo_clinical.silver.clinical_observations
  COMMENT 'Cleaned, typed, de-identified clinical observations'
  AS
  SELECT
    sha2(concat(patient_ref, ':lead-opt-deid-salt'), 256) AS patient_pseudonym,
    drug_code,
    observation_type,
    value,
    effective_ts
  FROM lead_opt_demo_clinical.bronze.ehr_compositions_raw
  WHERE drug_code IS NOT NULL
    AND observation_type IS NOT NULL
    AND effective_ts IS NOT NULL;

-- Patient reference registry: distinct de-identified references only. No
-- demographic or identifying fields beyond the synthetic pseudonym itself.
CREATE OR REPLACE TABLE lead_opt_demo_clinical.silver.patient_ref_registry
  COMMENT 'Distinct de-identified patient references, no demographics'
  AS
  SELECT
    patient_pseudonym,
    count(*) AS n_observations,
    count(DISTINCT drug_code) AS n_drug_codes,
    min(effective_ts) AS first_seen,
    max(effective_ts) AS last_seen
  FROM lead_opt_demo_clinical.silver.clinical_observations
  GROUP BY patient_pseudonym;

-- ---------------------------------------------------------------------------
-- GRANTS — materially tighter than preclinical (prompt 01 granted SELECT on the
-- WHOLE preclinical silver SCHEMA to the ingest SP + app SP). Here:
--   * NO schema-level SELECT to anyone.
--   * TABLE-level SELECT on only the two tables, to ONLY the ingest SP
--     (775366c2-...), which is the identity the stage-10 clinical-correlation
--     function runs as. That SP needs USE on the catalog/schema to navigate.
--   * The APP SP (eed3b02d-...), which reads the preclinical schema freely, is
--     granted NOTHING here — the app reaches clinical data only through the
--     scoped aggregate Genie view built in stage 12, never these base tables.
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG lead_opt_demo_clinical TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
GRANT USE SCHEMA ON SCHEMA lead_opt_demo_clinical.silver TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
GRANT SELECT ON TABLE lead_opt_demo_clinical.silver.clinical_observations TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
GRANT SELECT ON TABLE lead_opt_demo_clinical.silver.patient_ref_registry TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
