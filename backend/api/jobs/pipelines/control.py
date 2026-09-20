from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from ..run_all_repo import run_all_repo


class PipelineCanceled(Exception):
    """Raised to cooperatively abort pipeline execution."""


class PipelinePaused(Exception):
    """Raised to hand a paused job's remaining work back to the scheduler.

    A pause used to be implemented by sleeping inside the running task until
    the job resumed. That holds the Procrastinate concurrency slot for the
    whole pause, so with the default concurrency of 1 a single paused job
    starved every other review's jobs. Worse, the stale-chunk reaper would
    release the sleeping task's chunk back to 'todo' after ten minutes, and on
    resume that chunk was enqueued a second time while the original task also
    woke up, processing the same citations twice.

    Raising instead lets the caller release the unfinished work and return, so
    the worker is free during the pause and exactly one task owns the chunk.
    """


async def check_paused(job_id: str) -> None:
    """Raise if the job has been canceled or paused. Never blocks."""
    if await run_in_threadpool(run_all_repo.is_canceled, job_id):
        raise PipelineCanceled()
    if await run_in_threadpool(run_all_repo.is_paused, job_id):
        raise PipelinePaused()
