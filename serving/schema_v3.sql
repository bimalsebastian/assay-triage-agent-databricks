-- Stage 11: carry the three-state clinical correlation on the review queue.
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS clinical_correlation_state TEXT;
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS clinical_drug_code TEXT;
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS clinical_signal_detail TEXT;
