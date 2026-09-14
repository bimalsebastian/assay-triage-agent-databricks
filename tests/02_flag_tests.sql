-- Stage 02 unit tests — hand-built readings against check_toxicity_flag,
-- invoked with literal args (the function's supported call form). Covers a
-- low-concern assay (hERG, flag when BELOW threshold 1.0) and a high-concern
-- assay (LOGD, flag when ABOVE threshold 5.0): clearly below, clearly above,
-- and exactly at the boundary. Boundary is defined as NOT flagged (strict
-- inequality). Each row shows expected vs actual and a pass/fail.
WITH results AS (
  SELECT 'low_below_threshold_FLAG' AS test_name, TRUE AS expected,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00012','hERG_IC50',0.5,'uM').is_flagged AS actual
  UNION ALL SELECT 'low_above_threshold_ok', FALSE,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00012','hERG_IC50',5.0,'uM').is_flagged
  UNION ALL SELECT 'low_at_boundary_ok', FALSE,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00012','hERG_IC50',1.0,'uM').is_flagged
  UNION ALL SELECT 'high_above_threshold_FLAG', TRUE,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00001','LOGD_7_4',6.0,'').is_flagged
  UNION ALL SELECT 'high_below_threshold_ok', FALSE,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00001','LOGD_7_4',4.0,'').is_flagged
  UNION ALL SELECT 'high_at_boundary_ok', FALSE,
         lead_opt_demo.silver.check_toxicity_flag('CMPD00001','LOGD_7_4',5.0,'').is_flagged
)
SELECT test_name, expected, actual, (expected = actual) AS passed
FROM results
ORDER BY test_name;
