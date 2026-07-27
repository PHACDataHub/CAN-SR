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


def test_canonical_version_is_based_on_migration_files_not_legacy_markers():
    assert schema.MIGRATION_VERSION == '001_multi_reviewer_schema'


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
