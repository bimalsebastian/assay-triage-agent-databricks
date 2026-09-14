-- Stage 01 — Unity Catalog governance: curated silver tables from bronze.
-- Reads lead_opt_demo.bronze.assay_results_raw (produced by the stage-00
-- Lakeflow pipeline) and produces governed, typed silver tables with a
-- data-quality gate that quarantines bad rows instead of loading them.
-- Idempotent: safe to re-run (CREATE OR REPLACE).

CREATE SCHEMA IF NOT EXISTS lead_opt_demo.silver
  COMMENT 'Curated, governed assay data (stage 01)';

-- Curated assay_results: one row per reading, only rows passing the DQ gate.
-- Valid = has a compound id, a positive finite result, an assay name and a
-- timestamp, and is within a sane magnitude bound.
CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_results
  COMMENT 'Cleaned, typed assay readings from bronze, DQ-passing rows only'
  AS
  SELECT sample_id, compound_id, plate, well, replicate, assay_name,
         result_value, result_unit, acquired_ts, assay_protocol,
         operator_id, batch_guid, qc_flag
  FROM lead_opt_demo.bronze.assay_results_raw
  WHERE compound_id IS NOT NULL
    AND assay_name IS NOT NULL
    AND acquired_ts IS NOT NULL
    AND result_value IS NOT NULL
    AND result_value > 0
    AND result_value <= 100000;

-- Quarantine: the rows the DQ gate rejected, tagged with why. Nothing is
-- silently dropped — rejected rows land here for inspection.
CREATE OR REPLACE TABLE lead_opt_demo.silver.assay_results_quarantine
  COMMENT 'Rows rejected by the stage-01 DQ gate, with reason'
  AS
  SELECT *,
    CASE
      WHEN compound_id IS NULL THEN 'null_compound_id'
      WHEN assay_name IS NULL THEN 'null_assay_name'
      WHEN acquired_ts IS NULL THEN 'null_acquired_ts'
      WHEN result_value IS NULL THEN 'null_result_value'
      WHEN result_value <= 0 THEN 'nonpositive_result_value'
      WHEN result_value > 100000 THEN 'out_of_range_high'
      ELSE 'unknown'
    END AS quarantine_reason
  FROM lead_opt_demo.bronze.assay_results_raw
  WHERE NOT (
    compound_id IS NOT NULL
    AND assay_name IS NOT NULL
    AND acquired_ts IS NOT NULL
    AND result_value IS NOT NULL
    AND result_value > 0
    AND result_value <= 100000
  );

-- Compound registry: distinct compounds observed, with a clearly-synthetic
-- placeholder structure identifier (no real structures are used).
CREATE OR REPLACE TABLE lead_opt_demo.silver.compound_registry
  COMMENT 'Distinct compounds seen in assay data, structure id is a synthetic placeholder'
  AS
  SELECT
    compound_id,
    concat('SYNTH-INCHIKEY-', upper(substr(md5(compound_id), 1, 20))) AS structure_id_placeholder,
    TRUE AS structure_is_synthetic_placeholder,
    count(*) AS n_readings,
    count(DISTINCT assay_name) AS n_assays,
    min(acquired_ts) AS first_seen,
    max(acquired_ts) AS last_seen
  FROM lead_opt_demo.silver.assay_results
  GROUP BY compound_id;

-- Toxicology reference thresholds. SYNTHETIC reference data generated for this
-- demo (not sourced from any real tox database) — per-assay concern threshold
-- and direction that stage 03 compares new readings against.
CREATE OR REPLACE TABLE lead_opt_demo.silver.tox_reference
  COMMENT 'SYNTHETIC per-assay toxicity/ADMET concern thresholds (stage 03 input)'
  AS
  SELECT * FROM VALUES
    ('hERG_IC50',   'low',  1.0,   'uM',        'IC50 below threshold indicates cardiac hERG channel liability', TRUE),
    ('CYP3A4_IC50', 'low',  1.0,   'uM',        'Low IC50 indicates strong CYP3A4 inhibition and DDI risk',      TRUE),
    ('KINETIC_SOL', 'low',  10.0,  'uM',        'Low kinetic solubility indicates formulation and exposure risk', TRUE),
    ('CACO2_PAPP',  'low',  1.0,   '1e-6cm/s',  'Low apparent permeability indicates poor absorption',           TRUE),
    ('LOGD_7_4',    'high', 5.0,   '',          'High logD indicates excessive lipophilicity',                   TRUE)
  AS t(assay_name, concern_direction, concern_threshold, unit, rationale, is_synthetic);

-- Least-privilege grants. The service principal that backs the Genie space and
-- the flagging function (stages 02/04) gets READ ONLY on the silver schema;
-- it is never granted MODIFY/write. Write stays with the schema owner (the
-- pipeline/build identity).
GRANT USE CATALOG ON CATALOG lead_opt_demo TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
GRANT USE SCHEMA ON SCHEMA lead_opt_demo.silver TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
GRANT SELECT ON SCHEMA lead_opt_demo.silver TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
