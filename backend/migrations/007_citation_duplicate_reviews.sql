CREATE TABLE IF NOT EXISTS citation_duplicate_reviews (
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    group_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('confirmed_duplicate', 'not_duplicate', 'deferred')),
    survivor_id BIGINT,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sr_id, citation_table_name, group_id)
);

CREATE INDEX IF NOT EXISTS citation_duplicate_reviews_survivor_idx
    ON citation_duplicate_reviews (sr_id, citation_table_name, survivor_id);
