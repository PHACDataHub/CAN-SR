CREATE TABLE IF NOT EXISTS citation_deduplication_preferences (
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    fields JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sr_id, citation_table_name, user_id)
);

ALTER TABLE citation_deduplication_preferences ADD COLUMN IF NOT EXISTS threshold NUMERIC NOT NULL DEFAULT 0.70 CHECK (threshold IN (0.50, 0.70, 0.80));
