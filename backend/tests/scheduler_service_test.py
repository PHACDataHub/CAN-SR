from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from api.jobs.run_all_tasks import recover_and_enqueue_stale_chunks
from api.jobs.scheduler_service import InvalidJobTransition
from api.jobs.scheduler_service import SchedulerService


class FakeRepository:
    def __init__(self, status: str = 'queued', active_jobs: int = 1):
        self.job = {'job_id': 'job-1', 'status': status}
        self.active_jobs = active_jobs
        self.transitions: list[str] = []

    def count_active_jobs(self) -> int:
        return self.active_jobs

    def get_job(self, job_id: str):
        return self.job if job_id == 'job-1' else None

    def set_status(self, job_id: str, status: str, *, error=None) -> None:
        self.job['status'] = status
        self.transitions.append(status)

    def mark_canceled(self, job_id: str) -> None:
        self.set_status(job_id, 'canceled')


class SchedulerServiceTests(unittest.TestCase):
    def test_prefetch_splits_workers_across_active_jobs(self):
        service = SchedulerService(
            FakeRepository(active_jobs=3), worker_count=8,
        )
        self.assertEqual(service.compute_prefetch(), 2)

    def test_prefetch_is_bounded_and_at_least_one(self):
        self.assertEqual(
            SchedulerService(
                FakeRepository(active_jobs=0),
                worker_count=100,
            ).compute_prefetch(),
            20,
        )
        self.assertEqual(
            SchedulerService(
                FakeRepository(active_jobs=100),
                worker_count=2,
            ).compute_prefetch(),
            1,
        )

    def test_item_sanitization_preserves_order_and_removes_duplicates(self):
        self.assertEqual(
            SchedulerService.sanitize_item_ids([3, 1, 3, 2]),
            [3, 1, 2],
        )

    def test_lifecycle(self):
        repo = FakeRepository('running')
        service = SchedulerService(repo)
        self.assertEqual(service.pause('job-1'), 'paused')
        self.assertEqual(service.resume('job-1'), 'running')
        self.assertEqual(service.cancel('job-1'), 'canceled')
        self.assertEqual(repo.transitions, ['paused', 'running', 'canceled'])

    def test_terminal_job_cannot_be_resumed(self):
        service = SchedulerService(FakeRepository('finished'))
        self.assertEqual(service.resume('job-1'), 'finished')

    def test_only_visible_terminal_job_can_be_dismissed(self):
        service = SchedulerService(FakeRepository('running'))
        with self.assertRaises(InvalidJobTransition):
            service.dismiss('job-1')

        repo = FakeRepository('finished')
        self.assertEqual(SchedulerService(repo).dismiss('job-1'), 'done')


class RecoveryRepository:
    def __init__(self):
        self.released = []

    def recover_stale_chunk_ids(self, timeout_minutes):
        return [('job-1', 11), ('job-2', 22)]

    def release_chunk_claim(self, chunk_id, *, error):
        self.released.append((chunk_id, error))


class SchedulerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovered_chunks_are_reenqueued(self):
        repository = RecoveryRepository()
        enqueue = AsyncMock()
        count = await recover_and_enqueue_stale_chunks(
            10, repository=repository, enqueue_chunk=enqueue,
        )
        self.assertEqual(count, 2)
        self.assertEqual(enqueue.await_count, 2)
        self.assertEqual(repository.released, [])

    async def test_failed_reenqueue_releases_claim(self):
        repository = RecoveryRepository()
        enqueue = AsyncMock(side_effect=RuntimeError('queue unavailable'))
        with self.assertRaises(RuntimeError):
            await recover_and_enqueue_stale_chunks(
                10, repository=repository, enqueue_chunk=enqueue,
            )
        self.assertEqual(repository.released[0][0], 11)


if __name__ == '__main__':
    unittest.main()
