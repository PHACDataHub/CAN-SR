from __future__ import annotations

import unittest
from pathlib import Path


class SchedulerRepositoryGuardTests(unittest.TestCase):
    """Regression checks for the SQL safety predicates.

    Database integration coverage belongs in the PostgreSQL test suite; these
    fast checks prevent accidental removal of the critical guards meanwhile.
    """

    @classmethod
    def setUpClass(cls):
        repo_path = Path(__file__).resolve().parents[1] / 'api/jobs/run_all_repo.py'
        with repo_path.open(encoding='utf-8') as source:
            cls.source = source.read()

    def test_claim_locks_and_checks_parent_status(self):
        self.assertIn(
            'SELECT status FROM run_all_jobs WHERE id = %s FOR UPDATE',
            self.source,
        )
        self.assertIn("'queued', 'running', 'paused'", self.source)

    def test_chunk_completion_only_transitions_doing_chunks(self):
        self.assertGreaterEqual(
            self.source.count("AND status = 'doing'"),
            2,
        )

    def test_stale_recovery_only_targets_active_jobs(self):
        self.assertIn('def recover_stale_chunks', self.source)
        self.assertIn("j.status IN ('queued', 'running', 'paused')", self.source)
        self.assertIn("c.status = 'doing'", self.source)


if __name__ == '__main__':
    unittest.main()