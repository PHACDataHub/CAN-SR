from __future__ import annotations

from pathlib import Path

from api.services import review_schema_service as schema


def test_migration_file_is_resolved_inside_backend():
    assert schema.MIGRATION_PATH == Path(__file__).resolve(
    ).parents[1] / 'migrations' / '001_multi_reviewer_schema.sql'
    assert schema.MIGRATION_PATH.is_file()


def test_migration_files_are_ordered():
    files = schema.migration_files()
    assert files == sorted(files)
    assert files[0].stem == '001_multi_reviewer_schema'
    assert files[1].stem == '002_citation_workspace_schema'
    assert files[2].stem == '003_citation_import_preview_mapping_decisions'
    assert files[3].stem == '004_systematic_review_memberships'
    assert files[4].stem == '005_citation_workspace_column_preferences'


def test_canonical_version_is_based_on_migration_files_not_legacy_markers():
    assert schema.MIGRATION_VERSION == '001_multi_reviewer_schema'


def test_citation_workspace_migration_contains_legacy_adoption_schema():
    migration = Path(__file__).resolve(
    ).parents[1] / 'migrations' / '002_citation_workspace_schema.sql'
    sql = migration.read_text(encoding='utf-8')
    for table in (
        'citation_import_batches', 'citation_import_batch_memberships',
        'citation_import_previews', 'citation_identities',
    ):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in sql
    assert 'REFERENCES citation_import_batches(id)' in sql


def test_mapping_decision_migration_is_additive():
    migration = Path(__file__).resolve(
    ).parents[1] / 'migrations' / '003_citation_import_preview_mapping_decisions.sql'
    assert 'ADD COLUMN IF NOT EXISTS mapping_decision JSONB' in migration.read_text(
        encoding='utf-8',
    )


def test_membership_role_migration_backfills_legacy_owners_and_members():
    migration = Path(__file__).resolve(
    ).parents[1] / 'migrations' / '004_systematic_review_memberships.sql'
    sql = migration.read_text(encoding='utf-8')
    assert 'CREATE TABLE IF NOT EXISTS systematic_review_memberships' in sql
    assert "role IN ('owner', 'member')" in sql
    assert 'jsonb_array_elements_text' in sql
    assert "'owner'" in sql
    assert 'systematic_review_membership_audit_events' in sql


def test_migration_checksum_is_deterministic():
    sql = 'CREATE TABLE foundation (id integer);'
    assert schema.migration_checksum(sql) == schema.migration_checksum(sql)
    assert len(schema.migration_checksum(sql)) == 64


def test_feature_is_disabled_by_default(monkeypatch):
    # The imported settings object is intentionally not mutated. This checks
    # the source-level default contract without requiring a database.
    config = Path(__file__).resolve().parents[1] / 'api' / 'core' / 'config.py'
    source = config.read_text(encoding='utf-8')
    assert "ENABLE_MULTI_REVIEWER_SCHEMA', 'false'" in source
    assert "AUTO_MIGRATE', 'false'" in source
