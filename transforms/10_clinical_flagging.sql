-- Stage 10 — extended flagging with clinical correlation.
--
-- Adds a second dimension to the preclinical flag: does the compound also have
-- a real-world clinical signal, via its crosswalked drug_code? "Matching
-- signal" for this synthetic build = an adverse_reaction observation exists for
-- the crosswalked drug_code (deliberately planted on DRG-0012 in stage 07).
--
-- THREE DISTINCT STATES (never collapsed to a boolean):
--   no_mapping             — no crosswalk row, or the row has no drug_code
--   checked_no_correlation — mapped to a drug_code, but no adverse signal found
--   correlated             — mapped, and an adverse_reaction signal was found
-- "no clinical data to check against" (no_mapping) is deliberately distinct
-- from "checked and found nothing" (checked_no_correlation).
--
-- SHAPE CHOICE: a companion table assay_flags_clinical keyed by compound_id
-- (not a column on assay_flags). Clinical correlation is per-COMPOUND, while
-- assay_flags is per-READING — a companion keeps each at its natural grain and
-- avoids rewriting the per-reading schema.

-- Single-compound scoring function (literal-arg form; used by unit tests).
CREATE OR REPLACE FUNCTION lead_opt_demo.silver.check_clinical_correlation(compound_id STRING)
RETURNS STRUCT<state STRING, drug_code STRING, crosswalk_confidence DOUBLE,
               n_adverse_obs BIGINT, signal_detail STRING>
COMMENT 'Clinical-correlation check for a compound via the compound-drug crosswalk. Three states: no_mapping / checked_no_correlation / correlated.'
RETURN
  SELECT named_struct(
    'state', CASE WHEN v.drug_code IS NULL THEN 'no_mapping'
                  WHEN v.n_adverse > 0 THEN 'correlated'
                  ELSE 'checked_no_correlation' END,
    'drug_code', v.drug_code,
    'crosswalk_confidence', v.conf,
    'n_adverse_obs', v.n_adverse,
    'signal_detail',
      CASE WHEN v.drug_code IS NULL
             THEN 'no crosswalk mapping (or unresolved identifier) for this compound'
           WHEN v.n_adverse > 0
             THEN concat('mapped to ', v.drug_code, ' — adverse_reaction signal: ', v.terms)
           ELSE concat('mapped to ', v.drug_code, ' — checked clinical data, no adverse_reaction found')
      END
  )
  FROM (
    SELECT
      (SELECT max(drug_code) FROM lead_opt_demo.silver.compound_drug_crosswalk
         WHERE compound_id = check_clinical_correlation.compound_id) AS drug_code,
      (SELECT max(confidence) FROM lead_opt_demo.silver.compound_drug_crosswalk
         WHERE compound_id = check_clinical_correlation.compound_id) AS conf,
      (SELECT count(*) FROM lead_opt_demo_clinical.silver.clinical_observations co
         JOIN lead_opt_demo.silver.compound_drug_crosswalk xw ON xw.drug_code = co.drug_code
        WHERE xw.compound_id = check_clinical_correlation.compound_id
          AND co.observation_type = 'adverse_reaction') AS n_adverse,
      (SELECT concat_ws(', ', collect_set(co.value))
         FROM lead_opt_demo_clinical.silver.clinical_observations co
         JOIN lead_opt_demo.silver.compound_drug_crosswalk xw ON xw.drug_code = co.drug_code
        WHERE xw.compound_id = check_clinical_correlation.compound_id
          AND co.observation_type = 'adverse_reaction') AS terms
  ) v;

GRANT EXECUTE ON FUNCTION lead_opt_demo.silver.check_clinical_correlation TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;

-- Batch: one row per flagged compound with its clinical-correlation state,
-- applying the identical rule set-based (a table-reading UDF can't take per-row
-- column args — same Databricks limitation handled in stage 02).
CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_flags_clinical
  COMMENT 'Per-flagged-compound clinical correlation (stage 10). Three-state, keyed by compound_id.'
  AS
  WITH flagged AS (
    SELECT DISTINCT compound_id FROM lead_opt_demo.silver.assay_flags WHERE is_flagged
  ),
  xw AS (
    SELECT compound_id, max(drug_code) AS drug_code, max(confidence) AS conf
    FROM lead_opt_demo.silver.compound_drug_crosswalk GROUP BY compound_id
  ),
  adv AS (
    SELECT x.compound_id, count(*) AS n_adverse,
           concat_ws(', ', collect_set(co.value)) AS terms
    FROM lead_opt_demo.silver.compound_drug_crosswalk x
    JOIN lead_opt_demo_clinical.silver.clinical_observations co
      ON co.drug_code = x.drug_code AND co.observation_type = 'adverse_reaction'
    GROUP BY x.compound_id
  )
  SELECT
    f.compound_id,
    CASE WHEN xw.drug_code IS NULL THEN 'no_mapping'
         WHEN coalesce(adv.n_adverse, 0) > 0 THEN 'correlated'
         ELSE 'checked_no_correlation' END AS correlation_state,
    xw.drug_code,
    xw.conf AS crosswalk_confidence,
    coalesce(adv.n_adverse, 0) AS n_adverse_obs,
    CASE WHEN xw.drug_code IS NULL
           THEN 'no crosswalk mapping (or unresolved identifier) for this compound'
         WHEN coalesce(adv.n_adverse, 0) > 0
           THEN concat('mapped to ', xw.drug_code, ' — adverse_reaction signal: ', adv.terms)
         ELSE concat('mapped to ', xw.drug_code, ' — checked clinical data, no adverse_reaction found')
    END AS signal_detail,
    current_timestamp() AS evaluated_ts
  FROM flagged f
  LEFT JOIN xw  ON xw.compound_id  = f.compound_id
  LEFT JOIN adv ON adv.compound_id = f.compound_id;

GRANT SELECT ON TABLE lead_opt_demo.silver.assay_flags_clinical TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
