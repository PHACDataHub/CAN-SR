from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from api.jobs.pipelines.control import PipelineCanceled
from api.jobs.pipelines.control import PipelinePaused
from api.jobs.scheduler_tasks import scheduler_chunk


def _repo_source() -> str:
    path = Path(__file__).resolve().parents[1] / 'api/jobs/run_all_repo.py'
    return path.read_text(encoding='utf-8')


class StaleReaperGuardTests(unittest.TestCase):
    """The reaper must measure staleness from progress, not from start time."""

    @classmethod
    def setUpClass(cls):
        cls.source = _repo_source()

    def test_reaper_uses_the_progress_heartbeat(self):
        self.assertIn(
            'COALESCE(progress_at, started_at, created_at) < (now() - make_interval(mins := %s))',
            self.source,
        )

    def test_reaper_leaves_paused_jobs_alone(self):
        # A pause is deliberate and makes no progress by definition, so it is
        # not evidence of a stuck job.
        self.assertIn("WHERE status IN ('running', 'queued')", self.source)
        self.assertNotIn(
            "WHERE status IN ('running', 'paused', 'queued')", self.source,
        )

    def test_progress_is_recorded_when_counts_or_phase_change(self):
        self.assertIn('progress_at = now()', self.source)
        self.assertIn(
            'ADD COLUMN IF NOT EXISTS progress_at TIMESTAMP WITH TIME ZONE',
            self.source,
        )

    def test_job_timestamps_are_generated_by_postgres(self):
        # A naive client-side timestamp is compared against now() by the
        # reaper and skews whenever the two clocks or timezones differ.
        self.assertIn('started_at = COALESCE(started_at, now())', self.source)
        self.assertIn(
            'finished_at = COALESCE(finished_at, now())', self.source,
        )


class FakeRepo:
    def __init__(self, *, paused_at: int | None = None):
        self._paused_at = paused_at
        self.calls = 0
        self.counted: list[int] = []
        self.released: tuple[int, list[int]] | None = None
        self.phases: list[str] = []

    # --- reads -------------------------------------------------------
    def get_chunk(self, chunk_id: int):
        return {'id': chunk_id, 'citation_ids': [1, 2, 3]}

    def get_job(self, job_id: str):
        return {
            'sr_id': 'sr-1', 'pipeline_key': 'screening', 'step': 'l1',
            'created_by': 'user-1', 'model': None, 'meta': {},
            'total': 3, 'done': 0, 'skipped': 0, 'failed': 0,
        }

    def is_canceled(self, job_id: str) -> bool:
        return False

    def is_paused(self, job_id: str) -> bool:
        self.calls += 1
        return self._paused_at is not None and self.calls > self._paused_at

    # --- writes ------------------------------------------------------
    def update_phase(self, job_id: str, phase: str) -> None:
        self.phases.append(phase)

    def inc_counts(self, job_id: str, *, done=0, skipped=0, failed=0) -> None:
        self.counted.append(done + skipped + failed)

    def release_chunk_for_pause(self, chunk_id: int, remaining_ids: list[int]) -> None:
        self.released = (chunk_id, list(remaining_ids))

    def mark_chunk_done(self, chunk_id: int) -> None:
        pass

    def mark_chunk_failed(self, chunk_id: int, *, error: str) -> None:
        pass

    def add_error(self, job_id: str, **kwargs) -> None:
        pass

    def set_status(self, job_id: str, status: str, *, error=None) -> None:
        pass


class PauseReleasesWorkTests(unittest.IsolatedAsyncioTestCase):
    """A paused job must free its worker and keep its work exactly once."""

    async def _run(self, repo, execute_item):
        import api.jobs.scheduler_tasks as tasks

        class FakePipeline:
            pipeline_key = 'screening'

            async def execute_item(self, context, work_item):
                return await execute_item(work_item)

            def format_phase(self, work_item):
                return f'citation {work_item}'

            def error_stage(self, context):
                return 'l1'

        class FakeRegistry:
            def get(self, key):
                return FakePipeline()

        import api.jobs.pipelines.control as control

        originals = (
            tasks.run_all_repo, tasks.pipeline_registry,
            tasks._load_sr_and_table, control.run_all_repo,
        )
        tasks.run_all_repo = repo
        tasks.pipeline_registry = lambda: FakeRegistry()
        tasks._load_sr_and_table = AsyncMock(return_value=({}, 'citations'))
        control.run_all_repo = repo
        try:
            await scheduler_chunk(
                'job-1', 7, enqueue_chunk=AsyncMock(),
            )
        finally:
            (
                tasks.run_all_repo, tasks.pipeline_registry,
                tasks._load_sr_and_table, control.run_all_repo,
            ) = originals

    async def test_pause_between_citations_releases_only_unstarted_work(self):
        repo = FakeRepo(paused_at=1)
        processed: list[int] = []

        async def execute(work_item):
            processed.append(work_item)
            from api.jobs.pipelines.base import PipelineOutcome
            return PipelineOutcome('done')

        await self._run(repo, execute)

        # The first citation completed; the rest went back to the scheduler
        # rather than being re-run alongside the original task.
        self.assertEqual(processed, [1])
        self.assertEqual(repo.released, (7, [2, 3]))
        self.assertEqual(len(repo.counted), 1)

    async def test_pause_inside_a_citation_keeps_it_as_outstanding_work(self):
        repo = FakeRepo()

        async def execute(work_item):
            raise PipelinePaused()

        await self._run(repo, execute)

        # Nothing was counted, so the citation is still owed.
        self.assertEqual(repo.counted, [])
        self.assertEqual(repo.released, (7, [1, 2, 3]))

    async def test_cancel_does_not_reschedule_work(self):
        repo = FakeRepo()

        async def execute(work_item):
            raise PipelineCanceled()

        await self._run(repo, execute)
        self.assertIsNone(repo.released)


if __name__ == '__main__':
    unittest.main()
