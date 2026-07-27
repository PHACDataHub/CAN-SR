-- CAN-SR multi-reviewer foundation schema.
-- This migration is additive: legacy citation tables and human_* columns are
-- intentionally not altered.

CREATE TABLE IF NOT EXISTS review_assignment_policies (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('l1', 'l2', 'extract')),
    default_granularity TEXT NOT NULL
        CHECK (default_granularity IN ('citation', 'criterion', 'parameter')),
    overlap SMALLINT NOT NULL CHECK (overlap BETWEEN 1 AND 3),
    eligible_reviewer_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    workload_targets JSONB NOT NULL DEFAULT '{}'::jsonb,
    visibility_rule TEXT NOT NULL DEFAULT 'after_own_validation',
    agreement_rule_version TEXT NOT NULL DEFAULT 'v1',
    criteria_revision INTEGER NOT NULL DEFAULT 1,
    due_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (sr_id, stage, version)
);

-- Policy versions are unique. The repository resolves the greatest version
-- for an SR/stage; PostgreSQL partial-index predicates cannot contain a
-- subquery, so “active” is intentionally a service-level concept.

CREATE TABLE IF NOT EXISTS review_assignments (
    id UUID PRIMARY KEY,
    policy_id UUID NOT NULL REFERENCES review_assignment_policies(id),
    sr_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('l1', 'l2', 'extract')),
    source_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    criterion_key TEXT,
    parameter_key TEXT,
    criteria_revision INTEGER NOT NULL,
    reviewer_id TEXT NOT NULL,
    slot SMALLINT NOT NULL CHECK (slot >= 1),
    source TEXT NOT NULL CHECK (source IN
        ('stage_default', 'bulk_rule', 'citation', 'criterion', 'parameter')),
    status TEXT NOT NULL CHECK (status IN ('active', 'removed', 'stale')),
    priority INTEGER NOT NULL DEFAULT 0,
    due_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (parameter_key IS NULL OR criterion_key IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_active_assignment_reviewer
    ON review_assignments (
        sr_id, stage, source_table_name, citation_id,
        COALESCE(criterion_key, ''), COALESCE(parameter_key, ''), reviewer_id
    ) WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_active_assignment_slot
    ON review_assignments (
        sr_id, stage, source_table_name, citation_id,
        COALESCE(criterion_key, ''), COALESCE(parameter_key, ''), slot
    ) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_review_assignment_reviewer
    ON review_assignments (sr_id, stage, reviewer_id, status);
CREATE INDEX IF NOT EXISTS ix_review_assignment_work_unit
    ON review_assignments (sr_id, stage, source_table_name, citation_id,
                           criterion_key, parameter_key);
CREATE INDEX IF NOT EXISTS ix_review_assignment_queue
    ON review_assignments (sr_id, stage, status, due_at);

CREATE TABLE IF NOT EXISTS review_validations (
    id UUID PRIMARY KEY,
    assignment_id UUID REFERENCES review_assignments(id),
    sr_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('l1', 'l2', 'extract')),
    source_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    criterion_key TEXT,
    parameter_key TEXT,
    criteria_revision INTEGER NOT NULL,
    reviewer_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (state IN
        ('draft', 'validated', 'returned', 'superseded', 'stale')),
    answer_json JSONB NOT NULL,
    explanation TEXT,
    evidence_json JSONB,
    source TEXT NOT NULL CHECK (source IN ('user', 'legacy_migration')),
    client_request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMPTZ,
    returned_at TIMESTAMPTZ,
    superseded_by UUID REFERENCES review_validations(id),
    version BIGINT NOT NULL DEFAULT 1,
    CHECK (parameter_key IS NULL OR criterion_key IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_validation_request
    ON review_validations (reviewer_id, client_request_id)
    WHERE client_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_current_validation
    ON review_validations (
        sr_id, stage, source_table_name, citation_id,
        COALESCE(criterion_key, ''), COALESCE(parameter_key, ''),
        reviewer_id, state
    ) WHERE state IN ('draft', 'validated');
CREATE INDEX IF NOT EXISTS ix_review_validation_reviewer
    ON review_validations (sr_id, stage, reviewer_id, state, validated_at);
CREATE INDEX IF NOT EXISTS ix_review_validation_work_unit
    ON review_validations (sr_id, stage, source_table_name, citation_id,
                           criterion_key, parameter_key, state);

CREATE TABLE IF NOT EXISTS reconciliation_cases (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('l1', 'l2', 'extract')),
    source_table_name TEXT NOT NULL,
    citation_id BIGINT NOT NULL,
    criterion_key TEXT,
    parameter_key TEXT,
    case_version INTEGER NOT NULL CHECK (case_version >= 1),
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'in_progress', 'resolved', 'reopened')),
    reason TEXT NOT NULL,
    detected_from_validation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_reviewer_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1,
    CHECK (parameter_key IS NULL OR criterion_key IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_active_reconciliation
    ON reconciliation_cases (
        sr_id, stage, source_table_name, citation_id,
        COALESCE(criterion_key, ''), COALESCE(parameter_key, '')
    ) WHERE status IN ('pending', 'in_progress', 'reopened');

CREATE TABLE IF NOT EXISTS reconciliation_decisions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES reconciliation_cases(id),
    case_version INTEGER NOT NULL,
    decided_by TEXT NOT NULL,
    final_answer_json JSONB NOT NULL,
    rationale TEXT NOT NULL,
    evidence_json JSONB,
    preferred_validation_id UUID REFERENCES review_validations(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_reconciliation_queue
    ON reconciliation_cases (sr_id, stage, status, updated_at);
