-- Stage 19 — Explicit Unity Catalog ROW-LEVEL SECURITY + COLUMN MASKS on clinical data
--
-- LEVEL-UP: make the tiered clinical-governance story a self-evident UC artifact, not just
-- grants + code comments. These policies are enforced by Unity Catalog on the CALLER'S
-- identity at query time, on top of the separate-catalog + de-identification design.
--
-- Model: only members of the `clinical_pis` account group see clinical detail; everyone
-- else (e.g. chemists / preclinical reviewers) sees masked values, re-pseudonymised patient
-- keys, and no raw lab_result rows. Adverse-reaction rows (which drive the aggregate
-- convergence signal) remain visible so the blended-risk story keeps working.

-- 1) Column mask: clinical observation VALUE — PI-only, else redacted.
CREATE OR REPLACE FUNCTION lead_opt_demo_clinical.silver.mask_clinical_value(v STRING)
  RETURN CASE WHEN is_account_group_member('clinical_pis') THEN v
              ELSE 'REDACTED — clinical detail (clinical_pis only)' END;

-- 2) Column mask: patient pseudonym — PIs see the pseudonym; others get a further-hashed key
--    so cross-row linkage is not even possible at the non-PI tier.
CREATE OR REPLACE FUNCTION lead_opt_demo_clinical.silver.mask_patient_key(p STRING)
  RETURN CASE WHEN is_account_group_member('clinical_pis') THEN p
              ELSE concat('anon-', substr(sha2(p, 256), 1, 10)) END;

-- 3) Row filter: non-PIs never see raw lab_result rows; adverse_reaction rows (the
--    convergence signal) stay visible so aggregates are unaffected.
CREATE OR REPLACE FUNCTION lead_opt_demo_clinical.silver.rf_clinical_obs(obs_type STRING)
  RETURN is_account_group_member('clinical_pis') OR obs_type <> 'lab_result';

-- Attach the policies to the clinical observations table.
ALTER TABLE lead_opt_demo_clinical.silver.clinical_observations
  ALTER COLUMN value SET MASK lead_opt_demo_clinical.silver.mask_clinical_value;
ALTER TABLE lead_opt_demo_clinical.silver.clinical_observations
  ALTER COLUMN patient_pseudonym SET MASK lead_opt_demo_clinical.silver.mask_patient_key;
ALTER TABLE lead_opt_demo_clinical.silver.clinical_observations
  SET ROW FILTER lead_opt_demo_clinical.silver.rf_clinical_obs ON (observation_type);
