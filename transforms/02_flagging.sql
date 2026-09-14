-- Stage 02 — intelligence layer: an auditable tox/ADMET flag.
--
-- DESIGN CHOICE: deterministic threshold rule, NOT an LLM (ai_query) call.
-- CLAUDE.md requires the flag be auditable ("show what it compared against,
-- not a black box") for this GxP-adjacent story. A threshold rule against the
-- synthetic tox_reference is reproducible and fully explainable; an LLM call
-- would be a flashier "GenAI" demo but not defensible as a flagging authority
-- here. Output carries the full reasoning (threshold, direction, margin,
-- compound history), not just a boolean.
--
-- SIGNATURE NOTE: assay_name is added to the prompt's
-- (compound_id, reading_value, reading_unit) — several assays share the unit
-- "uM" (hERG, CYP3A4, solubility), so the reading alone can't be matched to
-- the right reference threshold without knowing the assay.
--
-- SHAPE NOTE: the UC function reads tox_reference + assay_results, so (a real
-- Databricks limitation) it can only be invoked with literal/scalar arguments,
-- not per-row column arguments. It is therefore the single-reading scoring
-- interface (used by the app/Genie in later stages, and by the unit tests).
-- The batch below applies the IDENTICAL threshold rule set-based (a join) to
-- score every row into assay_flags.

-- ---------------------------------------------------------------------------
-- Single-reading scoring function (structured, explainable result).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lead_opt_demo.silver.check_toxicity_flag(
  compound_id  STRING,
  assay_name   STRING,
  reading_value DOUBLE,
  reading_unit STRING
)
RETURNS STRUCT<
  is_flagged BOOLEAN, assay_name STRING, reading_value DOUBLE, reading_unit STRING,
  concern_direction STRING, threshold DOUBLE, threshold_unit STRING, margin DOUBLE,
  compound_prior_n BIGINT, compound_prior_mean DOUBLE, is_synthetic_reference BOOLEAN,
  reason STRING>
COMMENT 'Deterministic, auditable tox/ADMET flag for a single reading: compares to the synthetic tox_reference threshold for its assay plus the compound history, returning the full reasoning. Invoke with literal args.'
RETURN
  SELECT named_struct(
    'is_flagged',
      CASE WHEN v.thr IS NULL THEN FALSE
           WHEN v.dir = 'low'  AND check_toxicity_flag.reading_value < v.thr THEN TRUE
           WHEN v.dir = 'high' AND check_toxicity_flag.reading_value > v.thr THEN TRUE
           ELSE FALSE END,
    'assay_name', check_toxicity_flag.assay_name,
    'reading_value', check_toxicity_flag.reading_value,
    'reading_unit', check_toxicity_flag.reading_unit,
    'concern_direction', v.dir,
    'threshold', v.thr,
    'threshold_unit', v.thr_unit,
    'margin', round(check_toxicity_flag.reading_value - v.thr, 4),
    'compound_prior_n', v.hist_n,
    'compound_prior_mean', round(v.hist_mean, 4),
    'is_synthetic_reference', coalesce(v.is_syn, FALSE),
    'reason',
      CASE
        WHEN v.thr IS NULL
          THEN concat('OK: no synthetic reference threshold defined for assay ', check_toxicity_flag.assay_name)
        WHEN (v.dir = 'low'  AND check_toxicity_flag.reading_value < v.thr)
          OR (v.dir = 'high' AND check_toxicity_flag.reading_value > v.thr)
          THEN concat('FLAGGED: ', check_toxicity_flag.assay_name, ' reading ',
                      cast(check_toxicity_flag.reading_value AS STRING), ' ', coalesce(check_toxicity_flag.reading_unit, ''),
                      ' breaches synthetic ', v.dir, '-concern threshold ',
                      cast(v.thr AS STRING), ' ', coalesce(v.thr_unit, ''),
                      ' (margin ', cast(round(check_toxicity_flag.reading_value - v.thr, 4) AS STRING),
                      '). Compound prior mean ', cast(round(coalesce(v.hist_mean, check_toxicity_flag.reading_value), 4) AS STRING),
                      ' over ', cast(v.hist_n AS STRING), ' historical readings.')
        ELSE concat('OK: ', check_toxicity_flag.assay_name, ' reading ',
                    cast(check_toxicity_flag.reading_value AS STRING), ' ', coalesce(check_toxicity_flag.reading_unit, ''),
                    ' within synthetic ', v.dir, '-concern threshold ',
                    cast(v.thr AS STRING), ' ', coalesce(v.thr_unit, ''),
                    ' (margin ', cast(round(check_toxicity_flag.reading_value - v.thr, 4) AS STRING), ').')
      END
  )
  FROM (
    SELECT
      (SELECT max(concern_threshold) FROM lead_opt_demo.silver.tox_reference
         WHERE assay_name = check_toxicity_flag.assay_name) AS thr,
      (SELECT max(concern_direction) FROM lead_opt_demo.silver.tox_reference
         WHERE assay_name = check_toxicity_flag.assay_name) AS dir,
      (SELECT max(unit) FROM lead_opt_demo.silver.tox_reference
         WHERE assay_name = check_toxicity_flag.assay_name) AS thr_unit,
      (SELECT bool_or(is_synthetic) FROM lead_opt_demo.silver.tox_reference
         WHERE assay_name = check_toxicity_flag.assay_name) AS is_syn,
      (SELECT count(*) FROM lead_opt_demo.silver.assay_results
         WHERE compound_id = check_toxicity_flag.compound_id
           AND assay_name = check_toxicity_flag.assay_name) AS hist_n,
      (SELECT avg(result_value) FROM lead_opt_demo.silver.assay_results
         WHERE compound_id = check_toxicity_flag.compound_id
           AND assay_name = check_toxicity_flag.assay_name) AS hist_mean
  ) v;

GRANT EXECUTE ON FUNCTION lead_opt_demo.silver.check_toxicity_flag TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;

-- ---------------------------------------------------------------------------
-- Batch job: score every current assay_results row into assay_flags using the
-- IDENTICAL threshold rule and reason text as the function above (set-based).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_flags
  COMMENT 'Per-reading tox/ADMET flags with explainable reason (stage 02 output)'
  AS
  WITH hist AS (
    SELECT compound_id, assay_name, count(*) AS n, avg(result_value) AS m
    FROM lead_opt_demo.silver.assay_results
    GROUP BY compound_id, assay_name
  )
  SELECT
    ar.compound_id,
    ar.sample_id AS reading_id,
    ar.assay_name,
    ar.result_value,
    ar.result_unit,
    CASE WHEN tr.concern_threshold IS NULL THEN FALSE
         WHEN tr.concern_direction = 'low'  AND ar.result_value < tr.concern_threshold THEN TRUE
         WHEN tr.concern_direction = 'high' AND ar.result_value > tr.concern_threshold THEN TRUE
         ELSE FALSE END AS is_flagged,
    CASE
      WHEN tr.concern_threshold IS NULL
        THEN concat('OK: no synthetic reference threshold defined for assay ', ar.assay_name)
      WHEN (tr.concern_direction = 'low'  AND ar.result_value < tr.concern_threshold)
        OR (tr.concern_direction = 'high' AND ar.result_value > tr.concern_threshold)
        THEN concat('FLAGGED: ', ar.assay_name, ' reading ',
                    cast(ar.result_value AS STRING), ' ', coalesce(ar.result_unit, ''),
                    ' breaches synthetic ', tr.concern_direction, '-concern threshold ',
                    cast(tr.concern_threshold AS STRING), ' ', coalesce(tr.unit, ''),
                    ' (margin ', cast(round(ar.result_value - tr.concern_threshold, 4) AS STRING),
                    '). Compound prior mean ', cast(round(h.m, 4) AS STRING),
                    ' over ', cast(h.n AS STRING), ' historical readings.')
      ELSE concat('OK: ', ar.assay_name, ' reading ',
                  cast(ar.result_value AS STRING), ' ', coalesce(ar.result_unit, ''),
                  ' within synthetic ', tr.concern_direction, '-concern threshold ',
                  cast(tr.concern_threshold AS STRING), ' ', coalesce(tr.unit, ''),
                  ' (margin ', cast(round(ar.result_value - tr.concern_threshold, 4) AS STRING), ').')
    END AS reason,
    tr.concern_direction,
    tr.concern_threshold AS threshold,
    tr.unit AS threshold_unit,
    round(ar.result_value - tr.concern_threshold, 4) AS margin,
    coalesce(h.n, 0) AS compound_prior_n,
    round(h.m, 4) AS compound_prior_mean,
    coalesce(tr.is_synthetic, FALSE) AS is_synthetic_reference,
    current_timestamp() AS evaluated_ts
  FROM lead_opt_demo.silver.assay_results ar
  LEFT JOIN lead_opt_demo.silver.tox_reference tr ON tr.assay_name = ar.assay_name
  LEFT JOIN hist h ON h.compound_id = ar.compound_id AND h.assay_name = ar.assay_name;

GRANT SELECT ON TABLE lead_opt_demo.silver.assay_flags TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
