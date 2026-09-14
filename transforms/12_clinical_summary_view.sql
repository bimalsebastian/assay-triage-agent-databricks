-- Stage 12 — aggregate/masked view for scoped clinical NL querying.
-- Compound-level ONLY: no patient_pseudonym, no raw clinical_observations rows,
-- no per-patient detail. Built from the already-aggregate assay_flags_clinical
-- (which is itself per-compound), so nothing patient-level can leak through it.
-- This is the ONLY clinical surface the clinical Genie room can reach.
CREATE OR REPLACE VIEW lead_opt_demo.silver.clinical_correlation_summary
  COMMENT 'Aggregate/masked clinical-correlation summary for NL querying. Compound-level only, no patient data.'
  AS
  SELECT
    compound_id,
    correlation_state,
    n_adverse_obs,
    CASE WHEN correlation_state = 'correlated'
           THEN 'adverse_reaction signal present in clinical data'
         WHEN correlation_state = 'checked_no_correlation'
           THEN 'clinical data checked, no adverse_reaction signal'
         ELSE 'no clinical mapping available for this compound'
    END AS signal_summary
  FROM lead_opt_demo.silver.assay_flags_clinical;

GRANT SELECT ON VIEW lead_opt_demo.silver.clinical_correlation_summary TO `eed3b02d-5fda-409a-96e9-240e2a11e377`;
