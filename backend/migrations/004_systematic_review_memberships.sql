-- Normalized, review-scoped roles. Existing users JSONB remains synchronized
-- during the compatibility period for legacy clients and queries.
CREATE TABLE IF NOT EXISTS systematic_review_memberships (
    sr_id TEXT NOT NULL REFERENCES systematic_reviews(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    added_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sr_id, member_id)
);
CREATE INDEX IF NOT EXISTS ix_systematic_review_memberships_member
    ON systematic_review_memberships (member_id, sr_id);
CREATE INDEX IF NOT EXISTS ix_systematic_review_memberships_owner
    ON systematic_review_memberships (sr_id, role) WHERE role = 'owner';

CREATE TABLE IF NOT EXISTS systematic_review_membership_audit_events (
    id UUID PRIMARY KEY,
    sr_id TEXT NOT NULL REFERENCES systematic_reviews(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('member_added', 'member_removed', 'role_changed')),
    actor_id TEXT NOT NULL,
    old_role TEXT CHECK (old_role IN ('owner', 'member')),
    new_role TEXT CHECK (new_role IN ('owner', 'member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_systematic_review_membership_audit_scope
    ON systematic_review_membership_audit_events (sr_id, created_at DESC);

-- Backfill is repeatable and makes the legacy primary owner an owner role.
INSERT INTO systematic_review_memberships (sr_id, member_id, role, added_by)
SELECT id, COALESCE(NULLIF(owner_email, ''), owner_id), 'owner', COALESCE(NULLIF(owner_email, ''), owner_id)
FROM systematic_reviews
WHERE COALESCE(NULLIF(owner_email, ''), owner_id) IS NOT NULL
ON CONFLICT (sr_id, member_id) DO UPDATE SET role = 'owner', updated_at = CURRENT_TIMESTAMP;

INSERT INTO systematic_review_memberships (sr_id, member_id, role, added_by)
SELECT sr.id, member.value, 'member', COALESCE(NULLIF(sr.owner_email, ''), sr.owner_id)
FROM systematic_reviews sr
CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(sr.users, '[]'::jsonb)) AS member(value)
WHERE member.value <> ''
ON CONFLICT (sr_id, member_id) DO NOTHING;
