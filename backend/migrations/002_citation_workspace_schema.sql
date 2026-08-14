-- CAN-SR citation workspace metadata.
-- Citation rows live in dynamically named tables. These shared tables retain
-- {sr_id, citation_table_name, citation_id} references without conventional
-- foreign keys; services validate that scope and row existence transactionally.

CREATE TABLE IF NOT EXISTS citation_import_batches (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('file', 'legacy_initial_dataset')),
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    display_filename TEXT,
    content_sha256 TEXT,
    schema_fingerprint TEXT,
    mapping_decision JSONB,
    state TEXT NOT NULL CHECK (state IN ('committed', 'failed', 'tombstoned')),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    existing_exact_match_count INTEGER NOT NULL DEFAULT 0 CHECK (existing_exact_match_count >= 0),
    invalid_count INTEGER NOT NULL DEFAULT 0 CHECK (invalid_count >= 0),
    error_summary TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TIMESTAMPTZ,
    tombstoned_at TIMESTAMPTZ,
    tombstoned_by TEXT,
    UNIQUE (sr_id, citation_table_name, content_sha256)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_citation_legacy_initial_batch
    ON citation_import_batches (sr_id, citation_table_name)
    WHERE source_type = 'legacy_initial_dataset';
CREATE INDEX IF NOT EXISTS ix_citation_import_batches_review
    ON citation_import_batches (sr_id, citation_table_name, created_at DESC);

CREATE TABLE IF NOT EXISTS citation_import_batch_memberships (
    batch_id UUID NOT NULL REFERENCES citation_import_batches(id),
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('inserted', 'existing_exact_match')),
    identity_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (batch_id, citation_id)
);
CREATE INDEX IF NOT EXISTS ix_citation_batch_memberships_citation
    ON citation_import_batch_memberships (sr_id, citation_table_name, citation_id);

CREATE TABLE IF NOT EXISTS citation_import_previews (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT,
    source_sha256 TEXT NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    proposed_mapping JSONB NOT NULL,
    validation_report JSONB NOT NULL,
    encrypted_staging_locator TEXT NOT NULL,
    staging_expires_at TIMESTAMPTZ NOT NULL,
    commit_key TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_batch_id UUID REFERENCES citation_import_batches(id),
    cancelled_at TIMESTAMPTZ,
    UNIQUE (sr_id, created_by, commit_key)
);
CREATE INDEX IF NOT EXISTS ix_citation_import_previews_expiry
    ON citation_import_previews (staging_expires_at);

CREATE TABLE IF NOT EXISTS citation_identities (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    identity_kind TEXT NOT NULL CHECK (identity_kind IN ('doi', 'external_id', 'bibliographic_fingerprint')),
    identifier_namespace TEXT,
    normalized_value TEXT NOT NULL,
    fingerprint_version TEXT,
    diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_citation_identity_per_citation
    ON citation_identities (
        sr_id, citation_table_name, citation_id, identity_kind,
        COALESCE(identifier_namespace, ''), normalized_value
    );
CREATE UNIQUE INDEX IF NOT EXISTS uq_citation_identity_doi
    ON citation_identities (sr_id, citation_table_name, normalized_value)
    WHERE identity_kind = 'doi' AND normalized_value <> '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_citation_identity_external_id
    ON citation_identities (sr_id, citation_table_name, identifier_namespace, normalized_value)
    WHERE identity_kind = 'external_id' AND normalized_value <> '';
CREATE INDEX IF NOT EXISTS ix_citation_identities_citation
    ON citation_identities (sr_id, citation_table_name, citation_id);

CREATE TABLE IF NOT EXISTS citation_audit_events (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    citation_id BIGINT,
    batch_id UUID REFERENCES citation_import_batches(id),
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_citation_audit_events_scope
    ON citation_audit_events (sr_id, citation_table_name, citation_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_citation_legacy_adoption_audit
    ON citation_audit_events (batch_id, event_type)
    WHERE event_type = 'legacy_table_adopted';

CREATE TABLE IF NOT EXISTS citation_deletion_tombstones (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    deleted_by TEXT NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    impact_snapshot JSONB NOT NULL,
    UNIQUE (sr_id, citation_table_name, citation_id)
);

CREATE TABLE IF NOT EXISTS citation_deduplication_configs (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    selected_columns JSONB NOT NULL,
    look_ahead SMALLINT NOT NULL CHECK (look_ahead BETWEEN 1 AND 12),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS citation_duplicate_candidates (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    citation_table_name TEXT NOT NULL,
    left_citation_id BIGINT NOT NULL,
    right_citation_id BIGINT NOT NULL,
    config_id UUID REFERENCES citation_deduplication_configs(id),
    score NUMERIC(6, 5),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (left_citation_id < right_citation_id),
    UNIQUE (sr_id, citation_table_name, left_citation_id, right_citation_id)
);

CREATE TABLE IF NOT EXISTS citation_duplicate_resolutions (
    id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES citation_duplicate_candidates(id),
    resolution TEXT NOT NULL CHECK (resolution IN ('not_duplicate', 'related', 'merge_deferred')),
    decided_by TEXT NOT NULL,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
