-- Stage 18 — ADVISORY AI recommendation (Gen AI, ai_query) over the deterministic flags
--
-- DESIGN CHOICE: this is the FIRST and ONLY use of ai_query()/an LLM in the build,
-- and it is deliberately ADVISORY. The flagging AUTHORITY remains the deterministic
-- UC function check_toxicity_flag (transforms/02_flagging.sql) — see DESIGN_DECISIONS.md #1.
-- Here the LLM only turns already-computed, deterministic facts (the flag reason text +
-- the clinical correlation state) into a natural-language recommended NEXT ACTION for the
-- reviewer. It invents no data. Every recommendation is logged with its exact input prompt,
-- the model endpoint, and a timestamp, so the audit trail now covers AI-generated GUIDANCE
-- as well as the human resolution decisions already logged in Lakebase.
--
-- Grounding: one row per open-flagged compound, joined to its clinical correlation state.
-- Model: databricks-meta-llama-3-3-70b-instruct (pay-per-token FM API, batch-inference capable).

CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_flag_recommendations AS
WITH flagged AS (
  SELECT
    compound_id,
    COUNT(*)                                                          AS n_flags,
    array_join(collect_list(concat(assay_name, ' ', cast(round(result_value,3) AS string),
                                    ' vs threshold ', cast(threshold AS string),
                                    ' (margin ', cast(round(margin,3) AS string), ')')), '; ')  AS breaches,
    array_join(array_distinct(collect_list(reason)), ' || ')          AS reason_text
  FROM lead_opt_demo.silver.assay_flags
  WHERE is_flagged = true
  GROUP BY compound_id
),
joined AS (
  SELECT
    f.compound_id, f.n_flags, f.breaches, f.reason_text,
    coalesce(c.correlation_state, 'no_mapping')                        AS correlation_state,
    c.n_adverse_obs, c.signal_detail
  FROM flagged f
  LEFT JOIN lead_opt_demo.silver.assay_flags_clinical c
    ON c.compound_id = f.compound_id
),
prompted AS (
  SELECT *,
    concat(
      'You are assisting a pharma lead-optimization reviewer. This recommendation is ADVISORY only; ',
      'a deterministic rule already made the flag decision — do not contradict it or invent data. ',
      'Compound ', compound_id, ' has ', cast(n_flags AS string), ' flagged assay reading(s). ',
      'Deterministic flag reasoning: ', reason_text, '. ',
      'Assay breaches: ', breaches, '. ',
      'Clinical correlation state: ', correlation_state,
      CASE WHEN n_adverse_obs IS NOT NULL
           THEN concat(' (', cast(n_adverse_obs AS string), ' adverse observation(s): ', coalesce(signal_detail,''), ')')
           ELSE '' END, '. ',
      'Reply in exactly two lines, no preamble: ',
      'line 1 "ACTION: " then one of {deprioritize, escalate for confirmatory assay, monitor next cycle, proceed}; ',
      'line 2 "RATIONALE: " then one sentence grounded only in the facts above.'
    ) AS recommendation_input
  FROM joined
)
SELECT
  compound_id,
  n_flags,
  correlation_state,
  n_adverse_obs,
  recommendation_input,
  ai_query(
    'databricks-meta-llama-3-3-70b-instruct',
    recommendation_input,
    modelParameters => named_struct('temperature', 0.0, 'max_tokens', 160)
  )                                                                    AS recommendation,
  'databricks-meta-llama-3-3-70b-instruct'                             AS model_endpoint,
  current_timestamp()                                                  AS generated_ts
FROM prompted;

-- Audit note carried on the table itself.
COMMENT ON TABLE lead_opt_demo.silver.assay_flag_recommendations IS
  'ADVISORY AI recommendations (ai_query, Llama-3.3-70B) grounded in the deterministic flags + clinical correlation. Advisory only; deterministic check_toxicity_flag is the authority. Each row logs its exact input prompt, model endpoint and generated_ts for audit.';
