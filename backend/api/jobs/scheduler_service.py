from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol


ACTIVE_STATUSES = frozenset({'queued', 'running', 'paused'})
EXECUTION_TERMINAL_STATUSES = frozenset({'finished', 'failed', 'canceled', 'done'})
DISMISSIBLE_STATUSES = frozenset({'finished', 'failed'})


class SchedulerRepository(Protocol):
    """Persistence boundary used by generic scheduler orchestration."""

    def count_active_jobs(self) -> int: ...

    def get_job(self, job_id: str) -> dict[str, Any] | None: ...

    def set_status(
        self, job_id: str, status: str, *, error: str | None = None,
    ) -> None: ...

    def mark_canceled(self, job_id: str) -> None: ...


class InvalidJobTransition(ValueError):
    """Raised when a requested scheduler lifecycle transition is invalid."""


@dataclass(frozen=True)
class SchedulerService:
    """Generic scheduler lifecycle and fair-share calculations.

    Pipeline implementations own eligibility and citation side effects. This
    service deliberately knows nothing about screening, PDFs, or extraction.
    """

    repository: SchedulerRepository
    worker_count: int = 1
    max_prefetch: int = 20

    def compute_prefetch(self) -> int:
        try:
            active_jobs = int(self.repository.count_active_jobs() or 0)
        except Exception:
            active_jobs = 0
        workers = max(1, int(self.worker_count or 1))
        fair_share = max(1, workers // max(1, active_jobs))
        return min(max(1, int(self.max_prefetch)), fair_share)

    @staticmethod
    def sanitize_item_ids(values: list[int] | None) -> list[int] | None:
        if values is None:
            return None
        result: list[int] = []
        seen: set[int] = set()
        for value in values:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id in seen:
                continue
            seen.add(item_id)
            result.append(item_id)
        return result

    @staticmethod
    def build_chunks(item_ids: list[int], chunk_size: int = 1) -> list[list[int]]:
        size = max(1, int(chunk_size or 1))
        return [item_ids[i:i + size] for i in range(0, len(item_ids), size)]

    def pause(self, job_id: str) -> str:
        job = self._require_job(job_id)
        current = self._status(job)
        if current in EXECUTION_TERMINAL_STATUSES:
            return current
        if current not in ACTIVE_STATUSES:
            raise InvalidJobTransition(f"Cannot pause job in status '{current}'")
        if current != 'paused':
            self.repository.set_status(job_id, 'paused')
        return 'paused'

    def resume(self, job_id: str) -> str:
        job = self._require_job(job_id)
        current = self._status(job)
        if current in EXECUTION_TERMINAL_STATUSES:
            return current
        if current != 'paused':
            raise InvalidJobTransition(f"Cannot resume job in status '{current}'")
        self.repository.set_status(job_id, 'running')
        return 'running'

    def cancel(self, job_id: str) -> str:
        job = self._require_job(job_id)
        current = self._status(job)
        if current in EXECUTION_TERMINAL_STATUSES:
            return current
        if current not in ACTIVE_STATUSES:
            raise InvalidJobTransition(f"Cannot cancel job in status '{current}'")
        self.repository.mark_canceled(job_id)
        return 'canceled'

    def dismiss(self, job_id: str) -> str:
        job = self._require_job(job_id)
        current = self._status(job)
        if current == 'done':
            return current
        if current not in DISMISSIBLE_STATUSES:
            raise InvalidJobTransition(
                f"Only finished/failed jobs can be dismissed (status is '{current}')",
            )
        self.repository.set_status(job_id, 'done')
        return 'done'

    def _require_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job:
            raise LookupError(f'Job not found: {job_id}')
        return job

    @staticmethod
    def _status(job: dict[str, Any]) -> str:
        return str(job.get('status') or '').lower()