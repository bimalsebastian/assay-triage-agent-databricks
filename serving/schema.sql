-- Lakebase review_queue schema (database: lead_opt, schema: public).
-- Operational serving table for the review dashboard. Carries the stage-02
-- reasoning fields inline so the app never needs a second round-trip to Delta.
CREATE TABLE IF NOT EXISTS review_queue (
  reading_id           TEXT PRIMARY KEY,
  compound_id          TEXT NOT NULL,
  assay_name           TEXT NOT NULL,
  result_value         DOUBLE PRECISION,
  result_unit          TEXT,
  concern_direction    TEXT,
  threshold            DOUBLE PRECISION,
  threshold_unit       TEXT,
  margin               DOUBLE PRECISION,
  compound_prior_n     BIGINT,
  compound_prior_mean  DOUBLE PRECISION,
  reason               TEXT,
  status               TEXT NOT NULL DEFAULT 'open',   -- open | resolved | cleared
  flagged_ts           TIMESTAMPTZ,
  synced_ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_by          TEXT,
  resolved_ts          TIMESTAMPTZ,
  resolution_note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
