"""PostgreSQL scheduler invariants. Runs when the local test database is available."""
from __future__ import annotations

import os
import threading
import unittest
import uuid

import psycopg2


def _connect():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_TEST_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        dbname=os.getenv('POSTGRES_DATABASE', 'postgres'),
        user=os.getenv('POSTGRES_USER', 'admin'),
        password=os.getenv('POSTGRES_PASSWORD', 'password'),
        connect_timeout=2,
    )


class SchedulerPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.conn = _connect()
        except Exception as exc:
            raise unittest.SkipTest(f'PostgreSQL unavailable: {exc}')

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_skip_locked_claims_do_not_duplicate_work(self):
        claimed: list[int] = []
        lock = threading.Lock()

        # Use a normal uniquely named table because PostgreSQL temp tables are
        # connection-local and cannot exercise independent worker sessions.
        table = f'scheduler_claim_test_{uuid.uuid4().hex}'
        cur = self.conn.cursor()
        cur.execute(f'CREATE TABLE {table} (id INT PRIMARY KEY, status TEXT)')
        cur.executemany(f'INSERT INTO {table} VALUES (%s, %s)', [(i, 'todo') for i in range(20)])
        self.conn.commit()

        def worker():
            conn = _connect()
            try:
                while True:
                    cur = conn.cursor()
                    cur.execute(
                        f"""WITH next AS (SELECT id FROM {table} WHERE status='todo'
                            ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
                            UPDATE {table} t SET status='doing' FROM next
                            WHERE t.id=next.id RETURNING t.id""",
                    )
                    row = cur.fetchone()
                    conn.commit()
                    if not row:
                        break
                    with lock:
                        claimed.append(int(row[0]))
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        try:
            self.assertEqual(len(claimed), 20)
            self.assertEqual(len(set(claimed)), 20)
        finally:
            cur = self.conn.cursor()
            cur.execute(f'DROP TABLE {table}')
            self.conn.commit()
