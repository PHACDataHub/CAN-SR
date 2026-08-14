CREATE TABLE IF NOT EXISTS citation_duplicate_runs (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    dataset_revision JSONB NOT NULL,
    fields JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    result JSONB,
    error TEXT,
    requested_by TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS citation_duplicate_runs_lookup_idx
    ON citation_duplicate_runs (sr_id, citation_table_name, status, completed_at DESC);
