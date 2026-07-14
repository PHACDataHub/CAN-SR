from __future__ import annotations
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from fastapi.concurrency import run_in_threadpool
from ..core.config import settings
from ..services.sr_db_service import srdb_service
from .pipelines.base import JobContext
from .pipelines.control import PipelineCanceled, wait_if_paused
from .pipelines.pdf_linkage_pipeline import PdfLinkagePipeline
from .pipelines.registry import PipelineRegistry
from .pipelines.screening_executor import _eligible_ids, _run_extract_for_citation, _run_l1_for_citation, _run_l2_for_citation
from .pipelines.screening_pipeline import ScreeningPipeline
from .procrastinate_app import worker_concurrency
from .run_all_repo import run_all_repo
from .scheduler_service import SchedulerService

EnqueueChunk = Callable[..., Awaitable[Any]]
logger = logging.getLogger(__name__)


def compute_scheduler_prefetch() -> int:
    return SchedulerService(run_all_repo, worker_count=worker_concurrency()).compute_prefetch()


async def _load_sr_and_table(sr_id: str) -> tuple[dict[str, Any], str]:
    sr = await run_in_threadpool(srdb_service.get_systematic_review, sr_id, True)
    if not sr:
        raise RuntimeError(f"SR not found: {sr_id}")
    return sr, (sr.get('screening_db') or {}).get('table_name') or 'citations'


def pipeline_registry() -> PipelineRegistry:
    registry = PipelineRegistry()
    registry.register(
        ScreeningPipeline(
            eligible_ids=_eligible_ids,
            l1_executor=_run_l1_for_citation,
            l2_executor=_run_l2_for_citation,
            extract_executor=_run_extract_for_citation,
        ),
    )
    registry.register(PdfLinkagePipeline())
    return registry


def job_context(
    *, job_id: str, job: dict[str, Any], sr: dict[str, Any], table_name: str,
) -> JobContext:
    return JobContext(
        job_id=job_id,
        sr_id=str(job.get('sr_id')),
        sr=sr,
        table_name=table_name,
        created_by=str(job.get('created_by') or ''),
        model=job.get('model'),
        config=job.get('meta') or {},
        step=str(job.get('step') or ''),
    )


async def scheduler_start(
    job_id: str, *, enqueue_chunk: EnqueueChunk,
) -> None:
    """Compute eligible IDs and enqueue chunks."""
    try:
        job = await run_in_threadpool(run_all_repo.get_job, job_id)
        if not job:
            return
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            return

        sr_id = str(job.get('sr_id'))
        step = str(job.get('step'))
        pipeline_key = str(job.get('pipeline_key') or 'screening')
        # Chunk size is controlled via backend/.env (RUN_ALL_CHUNK_SIZE).
        # Default is 1 for maximum fairness/responsiveness.
        chunk_size = int(getattr(settings, 'RUN_ALL_CHUNK_SIZE', 1) or 1)
        chunk_size = max(1, min(100, chunk_size))
        sr, table_name = await _load_sr_and_table(sr_id)
        pipeline = pipeline_registry().get(pipeline_key)
        context = job_context(
            job_id=job_id, job=job, sr=sr, table_name=table_name,
        )
        ids = await pipeline.compute_work_items(context)
        await run_in_threadpool(run_all_repo.set_total, job_id, len(ids))
        logger.info(
            "Scheduler kickoff job_id=%s pipeline=%s step=%s eligible=%d",
            job_id, pipeline_key, step, len(ids),
        )

        # If user paused before kickoff, preserve paused status.
        if await run_in_threadpool(run_all_repo.is_paused, job_id):
            await run_in_threadpool(run_all_repo.set_status, job_id, 'paused')
        else:
            await run_in_threadpool(run_all_repo.set_status, job_id, 'running')
        await run_in_threadpool(run_all_repo.update_phase, job_id, f"enqueued {len(ids)}")
        if not ids:
            await run_in_threadpool(run_all_repo.set_status, job_id, 'finished')
            return

        # Fair scheduling: persist chunks and enqueue only the next chunk.
        chunks = [
            ids[i: i + chunk_size]
            for i in range(0, len(ids), chunk_size)
        ]
        await run_in_threadpool(run_all_repo.insert_chunks, job_id, chunks)

        if not await run_in_threadpool(run_all_repo.is_canceled, job_id):
            prefetch = await run_in_threadpool(compute_scheduler_prefetch)
            for _ in range(prefetch):
                next_chunk_id = await run_in_threadpool(
                    run_all_repo.claim_next_todo_chunk,
                    job_id,
                    prefetch=prefetch,
                )
                if next_chunk_id is None:
                    break
                await enqueue_chunk(job_id=job_id, chunk_id=int(next_chunk_id))

    except Exception as e:
        await run_in_threadpool(run_all_repo.set_status, job_id, 'failed', error=str(e))


async def scheduler_chunk(
    job_id: str, chunk_id: int, *, enqueue_chunk: EnqueueChunk,
) -> None:
    """Process a chunk sequentially.

    For fairness across multiple run-all jobs, we only keep a small number of
    chunks in-flight per job (prefetch). Each finished chunk schedules more work
    until the prefetch limit is reached.
    """
    chunk = await run_in_threadpool(run_all_repo.get_chunk, int(chunk_id))
    if not chunk:
        return
    citation_ids = chunk.get('citation_ids') or []
    if not isinstance(citation_ids, list):
        citation_ids = []
    logger.info(
        "Scheduler chunk started job_id=%s chunk_id=%s size=%d",
        job_id, chunk_id, len(citation_ids),
    )
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        return
    if await run_in_threadpool(run_all_repo.is_canceled, job_id):
        return

    sr_id = str(job.get('sr_id'))
    pipeline_key = str(job.get('pipeline_key') or 'screening')
    sr, table_name = await _load_sr_and_table(sr_id)
    pipeline = pipeline_registry().get(pipeline_key)
    context = job_context(
        job_id=job_id, job=job, sr=sr, table_name=table_name,
    )

    chunk_failed = False
    chunk_error: str | None = None

    for cid in citation_ids:
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            return
        await wait_if_paused(job_id)
        await run_in_threadpool(
            run_all_repo.update_phase, job_id, pipeline.format_phase(int(cid)),
        )

        try:
            await wait_if_paused(job_id)
            outcome = await pipeline.execute_item(context, int(cid))
            d, s, f = outcome.counts
            await run_in_threadpool(run_all_repo.inc_counts, job_id, done=d, skipped=s, failed=f)
        except PipelineCanceled:
            return
        except Exception as e:
            await run_in_threadpool(
                run_all_repo.add_error,
                job_id,
                citation_id=int(cid),
                stage=pipeline.error_stage(context),
                error=str(e),
            )
            await run_in_threadpool(run_all_repo.inc_counts, job_id, failed=1)
            chunk_failed = True
            chunk_error = str(e)

    logger.info(
        "Scheduler chunk finished job_id=%s chunk_id=%s size=%d",
        job_id, chunk_id, len(citation_ids),
    )

    # Mark chunk complete and schedule more work (up to prefetch).
    try:
        if chunk_failed:
            await run_in_threadpool(run_all_repo.mark_chunk_failed, int(chunk_id), error=chunk_error or 'chunk had failures')
        else:
            await run_in_threadpool(run_all_repo.mark_chunk_done, int(chunk_id))
    except Exception:
        # non-fatal
        pass

    # If the job is paused/canceled, do not enqueue next chunk yet.
    if await run_in_threadpool(run_all_repo.is_canceled, job_id):
        return
    await wait_if_paused(job_id)

    try:
        prefetch = await run_in_threadpool(compute_scheduler_prefetch)
        for _ in range(prefetch):
            next_chunk_id = await run_in_threadpool(
                run_all_repo.claim_next_todo_chunk,
                job_id,
                prefetch=prefetch,
            )
            if next_chunk_id is None:
                break
            await enqueue_chunk(job_id=job_id, chunk_id=int(next_chunk_id))
    except Exception:
        # non-fatal; job will still finish once counts reach total
        pass

    # If all chunks finished, we don't have a built-in counter. For phase 1, we consider
    # job done once done+skipped+failed >= total.
    try:
        job2 = await run_in_threadpool(run_all_repo.get_job, job_id)
        if job2:
            total = int(job2.get('total') or 0)
            done = int(job2.get('done') or 0)
            skipped = int(job2.get('skipped') or 0)
            failed = int(job2.get('failed') or 0)
            # Successful completion should remain visible in the UI until the
            # user dismisses it. We model that as a terminal-but-sticky status
            # called "finished". Dismissal transitions "finished" -> "done".
            if total > 0 and (done + skipped + failed) >= total and not await run_in_threadpool(run_all_repo.is_canceled, job_id):
                await run_in_threadpool(run_all_repo.set_status, job_id, 'finished')
    except Exception:
        pass
