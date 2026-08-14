"""Generic migration runner and read-only schema verifier.

Migrations are applied explicitly by deployment (or the CLI), while the API
startup path only verifies that the database is compatible with the code.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

MIGRATIONS_PATH = Path(__file__).resolve().parents[2] / 'migrations'
MIGRATION_TABLE = 'review_schema_migrations'
# Compatibility aliases retained for callers/tests from the first bootstrap.
MIGRATION_PATH = MIGRATIONS_PATH / '001_multi_reviewer_schema.sql'
MIGRATION_VERSION = MIGRATION_PATH.stem
REQUIRED_TABLES = {
    'review_schema_migrations', 'review_assignment_policies',
    'review_assignments', 'review_validations', 'reconciliation_cases',
    'reconciliation_decisions',
}


def migration_checksum(sql: str | None = None) -> str:
    text = sql if sql is not None else ''
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_PATH.glob('[0-9][0-9][0-9]_*.sql'))


class ReviewSchemaService:
    """Apply and verify the additive schema using an injected DB connection."""

    def __init__(self, connection_provider=None):
        self.connection_provider = connection_provider

    def _provider(self):
        if self.connection_provider is None:
            # Import lazily so disabled/shadow-mode tests and application
            # startup do not require database credentials just to import the
            # service module.
            from .postgres_auth import postgres_server
            self.connection_provider = postgres_server
        return self.connection_provider

    def _ensure_migration_table(self, cur) -> None:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS review_schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                checksum TEXT NOT NULL,
                app_version TEXT,
                execution_ms INTEGER
            )""",
        )
        # The first opt-in bootstrap created this table without execution_ms.
        # Keep upgrades additive so existing installations can adopt the
        # generic runner without a manual repair step.
        cur.execute(
            'ALTER TABLE review_schema_migrations '
            'ADD COLUMN IF NOT EXISTS execution_ms INTEGER',
        )

    def migrate(self, app_version: str | None = None) -> dict[str, Any]:
        """Apply all pending migrations in filename order.

        Each migration is committed independently. A failed migration is
        rolled back and later migrations are not attempted.
        """
        conn = self._provider().conn
        files = migration_files()
        if not files:
            raise RuntimeError(f'No migrations found in {MIGRATIONS_PATH}')
        applied: list[str] = []
        for path in files:
            version = path.stem
            sql = path.read_text(encoding='utf-8')
            checksum = hashlib.sha256(sql.encode('utf-8')).hexdigest()
            cur = conn.cursor()
            try:
                cur.execute(
                    'SELECT pg_advisory_xact_lock(hashtext(%s))',
                    ('can_sr_schema_migrations',),
                )
                self._ensure_migration_table(cur)
                cur.execute(
                    f'SELECT checksum FROM {MIGRATION_TABLE} WHERE version = %s',
                    (version,),
                )
                existing = cur.fetchone()
                if existing:
                    if existing[0] != checksum:
                        raise RuntimeError(
                            f'{version} checksum mismatch; refusing to continue',
                        )
                    conn.commit()
                    continue
                cur.execute(sql)
                cur.execute(
                    f'''INSERT INTO {MIGRATION_TABLE}
                        (version, checksum, app_version) VALUES (%s, %s, %s)''',
                    (version, checksum, app_version),
                )
                conn.commit()
                applied.append(version)
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        return {'applied': applied, **self.verify_schema(connection=conn)}

    def refresh_checksums(self) -> dict[str, Any]:
        """Rebaseline recorded checksums to the checked-in migration files.

        This is an explicit repair operation for databases affected by a
        formatter that modified migration files. Normal migration execution
        continues to reject checksum drift.
        """
        conn = self._provider().conn
        refreshed: list[str] = []
        cur = conn.cursor()
        try:
            self._ensure_migration_table(cur)
            for path in migration_files():
                version = path.stem
                checksum = migration_checksum(path.read_text(encoding='utf-8'))
                cur.execute(
                    f'''UPDATE {MIGRATION_TABLE}
                        SET checksum = %s WHERE version = %s''',
                    (checksum, version),
                )
                if cur.rowcount:
                    refreshed.append(version)
            conn.commit()
            return {'refreshed': refreshed}
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    # Backward-compatible name for callers of the original opt-in bootstrap.
    def ensure_schema(self, app_version: str | None = None) -> dict[str, Any]:
        return self.migrate(app_version)

    def verify_schema(self, connection=None) -> dict[str, Any]:
        conn = connection or self._provider().conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'public'
                     AND table_name = ANY(%s)""",
                (sorted(REQUIRED_TABLES),),
            )
            tables = {row[0] for row in cur.fetchall()}
            missing = sorted(REQUIRED_TABLES - tables)
            if missing:
                raise RuntimeError(
                    f'Multi-reviewer schema is incomplete: {missing}',
                )
            cur.execute(
                f'SELECT version FROM {MIGRATION_TABLE} ORDER BY version',
            )
            versions = [row[0] for row in cur.fetchall()]
            expected_versions = [path.stem for path in migration_files()]
            pending = [
                version for version in expected_versions if version not in versions
            ]
            if pending:
                raise RuntimeError(f'Database migrations pending: {pending}')
            # Older installations may retain the first bootstrap marker
            # (`multi_reviewer_v1`). It remains useful audit history, but must
            # not be treated as a newer migration than numeric file versions.
            legacy_versions = [
                version for version in versions if version not in expected_versions
            ]
            return {
                'version': expected_versions[-1] if expected_versions else None,
                'versions': versions,
                'legacy_versions': legacy_versions,
                'pending': pending,
                'tables': sorted(tables & REQUIRED_TABLES),
            }
        finally:
            cur.close()


review_schema_service = ReviewSchemaService()
