"""Live PostgreSQL invariants for external-ID citation import reconciliation.

Runs only when the configured local PostgreSQL test database is available. Each
test owns a unique review and dynamic citation table and removes both in teardown.
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading
import unittest
import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

import psycopg2
from api.services.citation_import_preview_service import CitationImportPreviewRepository


def _connect():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_TEST_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        dbname=os.getenv('POSTGRES_DATABASE', 'postgres'),
        user=os.getenv('POSTGRES_USER', 'admin'),
        password=os.getenv('POSTGRES_PASSWORD', 'password'),
        connect_timeout=2,
    )


class _Provider:
    def __init__(self, conn):
        self.conn = conn


class CitationImportPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.admin_conn = _connect()
        except Exception as exc:
            raise unittest.SkipTest(f'PostgreSQL unavailable: {exc}')
        migrations = Path(__file__).resolve().parents[1] / 'migrations'
        cur = cls.admin_conn.cursor()
        try:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS systematic_reviews (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL,
                    screening_db JSONB, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
            )
            cur.execute(
                (migrations / '002_citation_workspace_schema.sql').read_text(encoding='utf-8'),
            )
            cur.execute(
                (migrations / '001_multi_reviewer_schema.sql').read_text(encoding='utf-8'),
            )
            cur.execute(
                (migrations / '003_citation_import_preview_mapping_decisions.sql').read_text(encoding='utf-8'),
            )
            cls.admin_conn.commit()
        except Exception:
            cls.admin_conn.rollback()
            raise
        finally:
            cur.close()

    @classmethod
    def tearDownClass(cls):
        cls.admin_conn.close()

    def setUp(self):
        token = uuid.uuid4().hex
        self.sr_id = f'import_pg_{token}'
        self.table_name = f'cit_{token}'
        cur = self.admin_conn.cursor()
        cur.execute(
            f'CREATE TABLE "{self.table_name}" (id SERIAL PRIMARY KEY, title TEXT, abstract TEXT)',
        )
        cur.execute(
            """INSERT INTO systematic_reviews (id, name, owner_id, screening_db)
               VALUES (%s, %s, %s, jsonb_build_object('table_name', %s))""",
            (self.sr_id, 'integration test', 'owner@example.test', self.table_name),
        )
        self.admin_conn.commit()
        cur.close()

    def tearDown(self):
        cur = self.admin_conn.cursor()
        try:
            cur.execute(
                'DELETE FROM reconciliation_decisions WHERE case_id IN (SELECT id FROM reconciliation_cases WHERE sr_id = %s)', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM reconciliation_cases WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM review_validations WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM review_assignments WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM citation_import_previews WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM citation_audit_events WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM citation_import_batch_memberships WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM citation_import_batches WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM citation_identities WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM systematic_reviews WHERE id = %s', (self.sr_id,),
            )
            cur.execute(f'DROP TABLE IF EXISTS "{self.table_name}"')
            self.admin_conn.commit()
        except Exception:
            self.admin_conn.rollback()
            raise
        finally:
            cur.close()

    def _create_preview(self, rows, *, source: bytes | None = None) -> tuple[str, dict]:
        source = source or uuid.uuid4().bytes
        preview_id = str(uuid.uuid4())
        payload = {
            'filename': 'citations.csv', 'source_format': 'csv',
            'raw_file_base64': base64.b64encode(source).decode(), 'normalized_rows': rows,
        }
        cur = self.admin_conn.cursor()
        cur.execute(
            """INSERT INTO citation_import_previews
                (id, sr_id, citation_table_name, source_sha256, schema_fingerprint,
                 proposed_mapping, validation_report, encrypted_staging_locator,
                 staging_expires_at, commit_key, created_by)
               VALUES (%s, %s, %s, %s, 'test-schema', %s::jsonb, %s::jsonb, %s, %s, %s, %s)""",
            (
                preview_id, self.sr_id, self.table_name, hashlib.sha256(
                    source,
                ).hexdigest(),
                '{"title": "Title", "abstract": "Abstract"}',
                '{"valid_for_commit": true, "source_columns": ["Title", "Abstract"], "row_count": 1}',
                f'test/{preview_id}', datetime.now(timezone.utc) +
                timedelta(minutes=5), preview_id,
                'owner@example.test',
            ),
        )
        self.admin_conn.commit()
        cur.close()
        return preview_id, payload

    def _commit(self, preview_id, payload, conn=None):
        conn = conn or self.admin_conn
        return CitationImportPreviewRepository(connection_provider=_Provider(conn)).commit(
            preview_id, self.sr_id, 'owner@example.test',
            {'title': 'Title', 'abstract': 'Abstract'}, payload,
        )

    def _scalar(self, sql, params=()):
        cur = self.admin_conn.cursor()
        cur.execute(sql, params)
        value = cur.fetchone()[0]
        cur.close()
        return value

    def test_external_id_only_duplicate_and_namespace_isolation(self):
        first_id, first = self._create_preview([
            {'Title': 'Original', 'Abstract': 'Original abstract', 'PMID': 'PMID: 123'},
        ])
        second_id, second = self._create_preview([
            {'Title': 'Changed', 'Abstract': 'Changed abstract', 'PubMed ID': '123'},
        ])
        third_id, third = self._create_preview([
            {
                'Title': 'Separate system',
                'Abstract': 'Separate abstract', 'Scopus EID': '123',
            },
        ])

        self.assertEqual(self._commit(first_id, first)['inserted_count'], 1)
        duplicate = self._commit(second_id, second)
        self.assertEqual(
            (
                duplicate['inserted_count'],
                duplicate['existing_exact_match_count'],
            ), (0, 1),
        )
        self.assertEqual(self._commit(third_id, third)['inserted_count'], 1)
        self.assertEqual(
            self._scalar(
                f'SELECT count(*) FROM "{self.table_name}"',
            ), 2,
        )
        self.assertEqual(
            self._scalar(
                "SELECT count(*) FROM citation_identities WHERE sr_id = %s AND identity_kind = 'external_id'",
                (self.sr_id,),
            ), 2,
        )

    def test_cross_identity_conflict_rolls_back_before_any_writes(self):
        first_id, first = self._create_preview([
            {'Title': 'PubMed record', 'Abstract': 'A', 'PMID': '123'},
        ])
        second_id, second = self._create_preview([
            {'Title': 'Scopus record', 'Abstract': 'B', 'Scopus EID': '2-s2.0-1'},
        ])
        self._commit(first_id, first)
        self._commit(second_id, second)
        conflict_id, conflict = self._create_preview([
            {
                'Title': 'Conflicting', 'Abstract': 'C',
                'PMID': '123', 'Scopus EID': '2-s2.0-1',
            },
        ])

        with self.assertRaisesRegex(ValueError, 'ambiguous exact'):
            self._commit(conflict_id, conflict)
        self.assertEqual(
            self._scalar(
                f'SELECT count(*) FROM "{self.table_name}"',
            ), 2,
        )
        self.assertEqual(
            self._scalar(
                'SELECT count(*) FROM citation_import_batches WHERE sr_id = %s', (self.sr_id,),
            ), 2,
        )

    def test_retry_is_idempotent_and_trigger_failure_rolls_back_external_identity(self):
        preview_id, payload = self._create_preview([
            {'Title': 'Retry', 'Abstract': 'A', 'PMID': '123'},
        ])
        initial = self._commit(preview_id, payload)
        retry = self._commit(preview_id, payload)
        self.assertTrue(retry['idempotent'])
        self.assertEqual(retry['batch_id'], initial['batch_id'])
        self.assertEqual(
            self._scalar(
                f'SELECT count(*) FROM "{self.table_name}"',
            ), 1,
        )

        function_name = f'fail_external_identity_{uuid.uuid4().hex}'
        trigger_name = f'fail_external_identity_{uuid.uuid4().hex}'
        cur = self.admin_conn.cursor()
        cur.execute(
            f"""CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.identity_kind = 'external_id' AND NEW.normalized_value = 'force-rollback' THEN
                        RAISE EXCEPTION 'forced external identity failure';
                    END IF;
                    RETURN NEW;
                END $$""",
        )
        cur.execute(
            f'CREATE TRIGGER {trigger_name} BEFORE INSERT ON citation_identities '
            f'FOR EACH ROW EXECUTE FUNCTION {function_name}()',
        )
        self.admin_conn.commit()
        cur.close()
        try:
            failed_id, failed = self._create_preview([
                {'Title': 'Rollback', 'Abstract': 'B', 'PMID': 'force-rollback'},
            ])
            with self.assertRaisesRegex(Exception, 'forced external identity failure'):
                self._commit(failed_id, failed)
            self.assertEqual(
                self._scalar(
                    f'SELECT count(*) FROM "{self.table_name}"',
                ), 1,
            )
            self.assertEqual(
                self._scalar(
                    'SELECT count(*) FROM citation_import_batches WHERE sr_id = %s', (self.sr_id,),
                ), 1,
            )
            self.assertEqual(
                self._scalar(
                    'SELECT count(*) FROM citation_import_batch_memberships WHERE sr_id = %s', (self.sr_id,),
                ), 1,
            )
            self.assertEqual(
                self._scalar(
                    "SELECT count(*) FROM citation_identities WHERE sr_id = %s AND normalized_value = 'force-rollback'",
                    (self.sr_id,),
                ), 0,
            )
        finally:
            cur = self.admin_conn.cursor()
            cur.execute(
                f'DROP TRIGGER IF EXISTS {trigger_name} ON citation_identities',
            )
            cur.execute(f'DROP FUNCTION IF EXISTS {function_name}()')
            self.admin_conn.commit()
            cur.close()

    def test_concurrent_external_id_commits_produce_one_citation(self):
        first_id, first = self._create_preview([
            {'Title': 'Concurrent A', 'Abstract': 'A', 'PMID': '777'},
        ])
        second_id, second = self._create_preview([
            {'Title': 'Concurrent B', 'Abstract': 'B', 'PMID': '777'},
        ])
        results, errors = [], []
        gate = threading.Barrier(2)

        def worker(preview_id, payload):
            conn = _connect()
            try:
                gate.wait(timeout=5)
                results.append(self._commit(preview_id, payload, conn))
            except Exception as exc:  # surfaced as a test failure below
                errors.append(exc)
            finally:
                conn.close()

        threads = [
            threading.Thread(target=worker, args=(first_id, first)),
            threading.Thread(target=worker, args=(second_id, second)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(
            sorted(
                result['inserted_count']
                for result in results
            ), [0, 1],
        )
        self.assertEqual(
            sorted(
                result['existing_exact_match_count']
                for result in results
            ), [0, 1],
        )
        self.assertEqual(
            self._scalar(
                f'SELECT count(*) FROM "{self.table_name}"',
            ), 1,
        )
