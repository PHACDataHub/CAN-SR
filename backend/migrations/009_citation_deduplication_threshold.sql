ALTER TABLE citation_deduplication_preferences
    ADD COLUMN IF NOT EXISTS threshold NUMERIC NOT NULL DEFAULT 0.70
    CHECK (threshold IN (0.50, 0.70, 0.80));
