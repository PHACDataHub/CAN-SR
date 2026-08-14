"""Live PostgreSQL invariants for review member roles and co-ownership."""
from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import psycopg2.extras
from api.services import sr_db_service as srdb_module
from api.services.sr_db_service import SRDBService
from fastapi import HTTPException


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


class ReviewMembershipPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.conn = _connect()
        except Exception as exc:
            raise unittest.SkipTest(f'PostgreSQL unavailable: {exc}')
        cur = cls.conn.cursor()
        try:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS systematic_reviews (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL,
                    owner_email TEXT, users JSONB DEFAULT '[]'::jsonb,
                    visible BOOLEAN DEFAULT TRUE, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
            )
            cur.execute(
                'ALTER TABLE systematic_reviews ADD COLUMN IF NOT EXISTS owner_email TEXT',
            )
            cur.execute(
                "ALTER TABLE systematic_reviews ADD COLUMN IF NOT EXISTS users JSONB DEFAULT '[]'::jsonb",
            )
            migration = Path(__file__).resolve(
            ).parents[1] / 'migrations' / '004_systematic_review_memberships.sql'
            cur.execute(migration.read_text(encoding='utf-8'))
            cls.conn.commit()
        except Exception:
            cls.conn.rollback()
            raise
        finally:
            cur.close()
        cls.original_postgres_server = srdb_module.postgres_server
        srdb_module.postgres_server = _Provider(cls.conn)
        cls.service = SRDBService()

    @classmethod
    def tearDownClass(cls):
        srdb_module.postgres_server = cls.original_postgres_server
        cls.conn.close()

    def setUp(self):
        self.sr_id = f'membership_pg_{uuid.uuid4().hex}'
        self.owner = 'owner@example.test'
        self.member = 'member@example.test'
        self.co_owner = 'co-owner@example.test'

    def tearDown(self):
        cur = self.conn.cursor()
        try:
            cur.execute(
                'DELETE FROM systematic_review_membership_audit_events WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM systematic_review_memberships WHERE sr_id = %s', (
                    self.sr_id,
                ),
            )
            cur.execute(
                'DELETE FROM systematic_reviews WHERE id = %s', (self.sr_id,),
            )
            self.conn.commit()
        finally:
            cur.close()

    def _insert_legacy_review(self, users=None):
        cur = self.conn.cursor()
        try:
            cur.execute(
                """INSERT INTO systematic_reviews (id, name, owner_id, owner_email, users)
                   VALUES (%s, %s, %s, %s, %s::jsonb)""",
                (
                    self.sr_id, 'membership integration', 'owner-stable-id', self.owner,
                    psycopg2.extras.Json(
                        users if users is not None else [
                            self.owner, self.member,
                        ],
                    ),
                ),
            )
            self.conn.commit()
        finally:
            cur.close()

    def _apply_backfill_for_scope(self):
        cur = self.conn.cursor()
        try:
            cur.execute(
                """INSERT INTO systematic_review_memberships (sr_id, member_id, role, added_by)
                   SELECT id, COALESCE(NULLIF(owner_email, ''), owner_id), 'owner', COALESCE(NULLIF(owner_email, ''), owner_id)
                   FROM systematic_reviews WHERE id = %s
                   ON CONFLICT (sr_id, member_id) DO UPDATE SET role = 'owner', updated_at = CURRENT_TIMESTAMP""",
                (self.sr_id,),
            )
            cur.execute(
                """INSERT INTO systematic_review_memberships (sr_id, member_id, role, added_by)
                   SELECT sr.id, member.value, 'member', COALESCE(NULLIF(sr.owner_email, ''), sr.owner_id)
                   FROM systematic_reviews sr
                   CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(sr.users, '[]'::jsonb)) AS member(value)
                   WHERE sr.id = %s AND member.value <> ''
                   ON CONFLICT (sr_id, member_id) DO NOTHING""",
                (self.sr_id,),
            )
            self.conn.commit()
        finally:
            cur.close()

    def _scalar(self, sql, params=()):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchone()[0]
        finally:
            cur.close()

    def test_backfill_promote_and_audit_membership_roles(self):
        self._insert_legacy_review()
        self._apply_backfill_for_scope()

        self.assertEqual(
            self.service.get_member_role(
                self.sr_id, self.owner,
            ), 'owner',
        )
        self.assertEqual(
            self.service.get_member_role(
                self.sr_id, self.member,
            ), 'member',
        )
        promoted = self.service.set_member_role(
            self.sr_id, self.member, 'owner', self.owner,
        )
        self.assertTrue(promoted['changed'])
        self.assertTrue(self.service.user_is_sr_owner(self.sr_id, self.member))
        self.assertEqual(
            self._scalar(
                'SELECT event_type FROM systematic_review_membership_audit_events WHERE sr_id = %s ORDER BY created_at DESC LIMIT 1',
                (self.sr_id,),
            ), 'role_changed',
        )

    def test_co_owner_is_recognized_as_owner_and_member_is_not(self):
        self._insert_legacy_review()
        self._apply_backfill_for_scope()
        self.service.set_member_role(
            self.sr_id, self.co_owner, 'owner', self.owner,
        )

        self.assertTrue(
            self.service.user_is_sr_owner(
                self.sr_id, self.co_owner,
            ),
        )
        self.assertFalse(
            self.service.user_is_sr_owner(
                self.sr_id, self.member,
            ),
        )

    def test_require_review_owner_rejects_database_backed_regular_member(self):
        self._insert_legacy_review()
        self._apply_backfill_for_scope()

        with self.assertRaises(HTTPException) as error:
            self.service.require_review_owner(self.sr_id, self.member)

        self.assertEqual(error.exception.status_code, 403)

    def test_final_owner_cannot_be_demoted_or_removed(self):
        self._insert_legacy_review(users=[self.owner])
        self._apply_backfill_for_scope()

        with self.assertRaisesRegex(ValueError, 'At least one owner'):
            self.service.set_member_role(
                self.sr_id, self.owner, 'member', self.owner,
            )
        with self.assertRaisesRegex(ValueError, 'At least one owner'):
            self.service.remove_member(self.sr_id, self.owner, self.owner)
        self.assertEqual(
            self.service.get_member_role(
                self.sr_id, self.owner,
            ), 'owner',
        )

    def test_co_owner_can_change_visibility_but_member_is_denied(self):
        self._insert_legacy_review()
        self._apply_backfill_for_scope()
        self.service.set_member_role(
            self.sr_id, self.co_owner, 'owner', self.owner,
        )

        result = self.service.set_visibility(self.sr_id, False, self.co_owner)
        self.assertEqual(result['visible'], False)
        with self.assertRaises(HTTPException) as error:
            self.service.set_visibility(self.sr_id, True, self.member)
        self.assertEqual(error.exception.status_code, 403)
        self.assertFalse(
            self._scalar(
                'SELECT visible FROM systematic_reviews WHERE id = %s', (
                    self.sr_id,
                ),
            ),
        )

    def test_audit_failure_rolls_back_new_membership_and_legacy_sync(self):
        self._insert_legacy_review(users=[self.owner])
        self._apply_backfill_for_scope()
        function = f'fail_membership_audit_{uuid.uuid4().hex}'
        trigger = f'fail_membership_audit_{uuid.uuid4().hex}'
        cur = self.conn.cursor()
        try:
            cur.execute(
                f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'forced membership audit failure'; END $$""",
            )
            cur.execute(
                f'CREATE TRIGGER {trigger} BEFORE INSERT ON systematic_review_membership_audit_events '
                f'FOR EACH ROW EXECUTE FUNCTION {function}()',
            )
            self.conn.commit()
            with self.assertRaisesRegex(Exception, 'forced membership audit failure'):
                self.service.set_member_role(
                    self.sr_id, self.member, 'member', self.owner,
                )
            self.assertIsNone(
                self.service.get_member_role(
                    self.sr_id, self.member,
                ),
            )
            self.assertEqual(
                self._scalar(
                    'SELECT users::text FROM systematic_reviews WHERE id = %s', (
                        self.sr_id,
                    ),
                ), '["owner@example.test"]',
            )
        finally:
            cur.execute(
                f'DROP TRIGGER IF EXISTS {trigger} ON systematic_review_membership_audit_events',
            )
            cur.execute(f'DROP FUNCTION IF EXISTS {function}()')
            self.conn.commit()
            cur.close()
