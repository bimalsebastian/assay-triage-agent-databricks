-- Stage 06 schema additions (Lakebase, database lead_opt).
-- A resolved item leaves the active review_queue, so its resolution is recorded
-- in a companion table that also powers the flag->resolve KPI.

CREATE TABLE IF NOT EXISTS resolved_items (
  reading_id         TEXT PRIMARY KEY,
  compound_id        TEXT NOT NULL,
  assay_name         TEXT NOT NULL,
  result_value       DOUBLE PRECISION,
  result_unit        TEXT,
  threshold          DOUBLE PRECISION,
  margin             DOUBLE PRECISION,
  reason             TEXT,
  resolution_reason  TEXT NOT NULL
    CHECK (resolution_reason IN
      ('false_positive', 'confirmed_concern', 'escalated_for_confirmatory_assay')),
  resolved_by        TEXT NOT NULL,
  resolved_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
  flagged_ts         TIMESTAMPTZ,        -- when the flag was created (from review_queue)
  resolution_note    TEXT
);

-- Keep the resolution_reason on the active row too, so the queue row itself
-- reflects why it left (review_queue rows are retained with status='resolved').
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS resolution_reason TEXT;
