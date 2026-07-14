from __future__ import annotations
import asyncio
from fastapi.concurrency import run_in_threadpool
from ..run_all_repo import run_all_repo

class PipelineCanceled(Exception):
    """Raised to cooperatively abort pipeline execution."""

async def wait_if_paused(job_id: str) -> None:
    while True:
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise PipelineCanceled()
        if not await run_in_threadpool(run_all_repo.is_paused, job_id):
            return
        await asyncio.sleep(0.5)
