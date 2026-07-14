from __future__ import annotations
from .procrastinate_app import PROCRASTINATE_APP
from .scheduler_tasks import scheduler_chunk, scheduler_start


@PROCRASTINATE_APP.task(queue='default')
async def run_all_start(job_id: str) -> None:
    """Compatibility wrapper retaining the legacy queued task name."""
    await scheduler_start(
        job_id, enqueue_chunk=run_all_chunk.defer_async,
    )


@PROCRASTINATE_APP.task(queue='default')
async def run_all_chunk(job_id: str, chunk_id: int) -> None:
    """Compatibility wrapper retaining the legacy queued task name."""
    await scheduler_chunk(
        job_id, chunk_id, enqueue_chunk=run_all_chunk.defer_async,
    )


async def recover_and_enqueue_stale_chunks(
    timeout_minutes: int = 10, *, repository=None, enqueue_chunk=None,
) -> int:
    """Recover stale claims and replace the queue tasks lost with workers."""
    from fastapi.concurrency import run_in_threadpool
    from .run_all_repo import run_all_repo

    repository = repository or run_all_repo
    enqueue_chunk = enqueue_chunk or run_all_chunk.defer_async
    recovered = await run_in_threadpool(
        repository.recover_stale_chunk_ids, timeout_minutes,
    )
    for job_id, chunk_id in recovered:
        try:
            await enqueue_chunk(job_id=job_id, chunk_id=chunk_id)
        except Exception:
            await run_in_threadpool(
                repository.release_chunk_claim,
                chunk_id,
                error='Failed to re-enqueue recovered chunk',
            )
            raise
    return len(recovered)


async def enqueue_available_chunks(job_id: str) -> int:
    """Fill a resumed job's fair-share queue slots."""
    from fastapi.concurrency import run_in_threadpool
    from .run_all_repo import run_all_repo
    from .scheduler_tasks import compute_scheduler_prefetch

    prefetch = await run_in_threadpool(compute_scheduler_prefetch)
    chunk_ids = await run_in_threadpool(
        run_all_repo.claim_available_chunks, job_id, prefetch=prefetch,
    )
    for chunk_id in chunk_ids:
        try:
            await run_all_chunk.defer_async(job_id=job_id, chunk_id=chunk_id)
        except Exception:
            await run_in_threadpool(
                run_all_repo.release_chunk_claim,
                chunk_id,
                error='Failed to enqueue resumed chunk',
            )
            raise
    return len(chunk_ids)
