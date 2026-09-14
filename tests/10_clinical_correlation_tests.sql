-- Stage 10 unit tests — three distinct, distinguishable clinical-correlation
-- outcomes, invoked with literal compound_ids:
--   CMPD00012 -> correlated              (mapped to DRG-0012, adverse signal planted)
--   CMPD00004 -> checked_no_correlation  (mapped to DRG-0004, only benign labs)
--   CMPD00024 -> no_mapping              (flagged, but no crosswalk row at all)
WITH results AS (
  SELECT 'CMPD00012_correlated' AS test_name, 'correlated' AS expected,
         lead_opt_demo.silver.check_clinical_correlation('CMPD00012').state AS actual
  UNION ALL SELECT 'CMPD00004_checked_no_correlation', 'checked_no_correlation',
         lead_opt_demo.silver.check_clinical_correlation('CMPD00004').state
  UNION ALL SELECT 'CMPD00024_no_mapping', 'no_mapping',
         lead_opt_demo.silver.check_clinical_correlation('CMPD00024').state
)
SELECT test_name, expected, actual, (expected = actual) AS passed
FROM results ORDER BY test_name;
