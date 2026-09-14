-- Stage 09 — compound-drug crosswalk (the two tracks converge here).
-- Lives in the PRECLINICAL catalog (the preclinical side looks outward to the
-- clinical identifier). Performs a real cross-catalog read: validates seed
-- drug_codes against lead_opt_demo_clinical.silver.clinical_observations and
-- seed compound_ids against lead_opt_demo.silver.compound_registry.
--
-- Identifier reconciliation is a genuine hard problem in translational
-- medicine: a real crosswalk must reconcile multiple identifier systems (INN,
-- product code, internal compound ID) and is rarely a clean 1:1 mapping. This
-- build's mapping is intentionally simplified synthetic data and says so
-- outright — it is NOT presented as having solved reconciliation. The seed
-- therefore includes a clean 1:1 case, an ambiguous multi-map, and an
-- unresolved (no clinical identifier) case.

CREATE OR REPLACE TABLE lead_opt_demo.silver.compound_drug_crosswalk
  COMMENT 'Compound<->drug identifier crosswalk. SYNTHETIC and intentionally simplified: real translational integrations reconcile multiple identifier systems (INN, product code, internal id) and are rarely clean 1:1. Includes ambiguous and unresolved cases on purpose.'
  AS
  WITH seed (compound_id, drug_code, mapping_source, confidence) AS (
    VALUES
      ('CMPD00012', 'DRG-0012', 'synthetic 1:1 by design',            1.0),
      ('CMPD00004', 'DRG-0004', 'synthetic 1:1 by design',            1.0),
      ('CMPD00008', 'DRG-0008', 'synthetic 1:1 by design',            1.0),
      ('CMPD00001', 'DRG-0001', 'synthetic 1:1 by design',            1.0),
      ('CMPD00006', 'DRG-0777', 'ambiguous multi-map (synthetic)',    0.5),
      ('CMPD00007', 'DRG-0777', 'ambiguous multi-map (synthetic)',    0.5),
      ('CMPD00014', NULL,       'unresolved - no clinical identifier', 0.0)
  ),
  clin_drugs AS (
    SELECT DISTINCT drug_code
    FROM lead_opt_demo_clinical.silver.clinical_observations   -- cross-catalog read
  ),
  comps AS (
    SELECT DISTINCT compound_id FROM lead_opt_demo.silver.compound_registry
  )
  SELECT
    s.compound_id,
    s.drug_code,
    s.mapping_source,
    s.confidence,
    (s.drug_code IS NULL OR s.drug_code IN (SELECT drug_code FROM clin_drugs))
      AS drug_code_seen_in_clinical,
    (s.compound_id IN (SELECT compound_id FROM comps))
      AS compound_seen_in_registry
  FROM seed s;

GRANT SELECT ON TABLE lead_opt_demo.silver.compound_drug_crosswalk TO `775366c2-e2bc-435c-af28-0cd5ca2386a0`;
