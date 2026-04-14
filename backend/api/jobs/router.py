from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..core.security import get_current_active_user
from ..core.cit_utils import load_sr_and_check
from ..services.sr_db_service import srdb_service
from ..services.azure_openai_client import azure_openai_client
from ..services.cit_db_service import cits_dp_service

from .run_all_repo import run_all_repo
from .procrastinate_app import cancel_enqueued_jobs_for_run_all, jobs_enabled, worker_concurrency

# Import task objects so we can enqueue via Task.defer_async (Procrastinate 3.2.x)
from .run_all_tasks import run_all_chunk, run_all_start

# Import tasks so Procrastinate can discover them.
from . import run_all_tasks  # noqa: F401


router = APIRouter()


def _compute_run_all_prefetch() -> int:
    """Compute fair-share prefetch.

    W = Procrastinate worker concurrency.
    J = number of active run-all jobs.

    Prefetch is capped to ensure a single job doesn't monopolize the global queue.
    """
    w = int(worker_concurrency() or 1)
    try:
        j = int(run_all_repo.count_active_jobs() or 0)
    except Exception:
        j = 0
    j = max(1, j)
    # Fair share: split workers across active jobs.
    pf = max(1, w // j)
    # Safety clamp
    return min(20, pf)


def _build_chunks(ids: list[int], chunk_size: int) -> list[list[int]]:
    if not ids:
        return []
    cs = max(1, int(chunk_size or 1))
    return [ids[i : i + cs] for i in range(0, len(ids), cs)]


def _is_unique_violation(exc: BaseException) -> bool:
    """Return True if this exception is a Postgres unique-constraint violation (23505)."""
    # psycopg2 may raise a specialized errors.UniqueViolation, or a generic
    # IntegrityError with pgcode set.
    try:
        if isinstance(exc, psycopg2.errors.UniqueViolation):
            return True
    except Exception:
        # Defensive: psycopg2 might not have errors in some environments.
        pass
    return getattr(exc, "pgcode", None) == "23505"


class RunAllStartRequest(BaseModel):
    step: str = Field(..., description="l1 | l2 | extract")
    model: Optional[str] = Field(None, description="LLM model name")
    force: bool = Field(False, description="If true, overwrite existing outputs")
    # NOTE: backend currently forces chunk_size=1 to ensure fair interleaving
    # of multiple active run-all jobs.
    chunk_size: int = Field(50, ge=1, le=500)
    citation_ids: Optional[list[int]] = Field(
        None,
        description="Optional explicit citation IDs to queue. If provided, backend queues exactly these (after sanitization).",
    )


@router.get("/run-all/active")
async def list_active_run_all(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """List active run-all jobs for SRs visible to current user."""
    # Ensure tables + index exist
    await run_in_threadpool(run_all_repo.ensure_tables)

    # Determine SRs user can see.
    user_email = str(current_user.get("email") or "")
    if not user_email:
        raise HTTPException(status_code=401, detail="Missing user identity")

    srs = await run_in_threadpool(srdb_service.list_systematic_reviews_for_user, user_email)
    sr_ids = [str(sr.get("id")) for sr in (srs or []) if sr and sr.get("id")]
    if not sr_ids:
        return {"jobs": []}

    jobs = await run_in_threadpool(run_all_repo.list_active_jobs_for_srs, sr_ids)

    # Attach SR name for nicer UI.
    sr_name_map = {str(sr.get("id")): sr.get("name") for sr in (srs or []) if sr and sr.get("id")}
    for j in jobs:
        sid = str(j.get("sr_id"))
        if sid in sr_name_map:
            j["sr_name"] = sr_name_map[sid]

    return {"jobs": jobs}


@router.post("/run-all/start")
async def start_run_all(
    sr_id: str,
    payload: RunAllStartRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    if not jobs_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background jobs are disabled. Set ENABLE_PROCRASTINATE=true.",
        )

    step = (payload.step or "").lower().strip()
    if step not in {"l1", "l2", "extract"}:
        raise HTTPException(status_code=400, detail="step must be one of: l1, l2, extract")

    # Authz: ensure user can access SR
    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load SR: {e}")

    # Legacy safety:
    # If legacy llm_* outputs exist but normalized agent runs are missing, we must
    # regenerate results to populate screening_agent_runs.
    # We enforce this by auto-enabling force overwrite.
    force = bool(payload.force)
    try:
        table_name = (screening or {}).get("table_name") or "citations"
        cp = (sr or {}).get("criteria_parsed") or {}
        if step in {"l1", "l2"}:
            legacy_needs = await run_in_threadpool(
                cits_dp_service.legacy_needs_rerun,
                sr_id=sr_id,
                table_name=table_name,
                criteria_parsed=cp,
                step=step,
            )
            if legacy_needs:
                force = True
    except Exception:
        # best-effort, do not block
        pass

    # Ensure our job tables exist
    await run_in_threadpool(run_all_repo.ensure_tables)

    # Fast path: if one exists, attach UI to it.
    # (The DB unique index below is still the race-safe guard.)
    existing = await run_in_threadpool(run_all_repo.get_active_job_for_sr, sr_id)
    if existing:
        return {
            "job_id": existing.get("job_id"),
            # new key (preferred)
            "already_running": True,
            # old key (backwards-compatible)
            "existing": True,
            "message_key": "screening.onlyOneJobAtATime",
            "message": "Only one job can be running at a time",
            "job": existing,
        }

    # Optional: caller provides explicit ids (single-request UI)
    raw_ids = payload.citation_ids or None
    sanitized_ids: Optional[list[int]] = None
    if raw_ids is not None:
        seen: set[int] = set()
        tmp: list[int] = []
        for v in raw_ids:
            try:
                i = int(v)
            except Exception:
                continue
            if i in seen:
                continue
            seen.add(i)
            tmp.append(i)
        sanitized_ids = tmp

    # Create job in queued state.
    # Option A semantics: total is the number of IDs requested.
    # (Missing PDFs for l2/extract are counted as skipped.)
    try:
        normalized_model = azure_openai_client.normalize_model_key(payload.model)
        job_id = await run_in_threadpool(
            run_all_repo.create_job,
            sr_id=sr_id,
            step=step,
            created_by=str(current_user.get("id") or ""),
            model=normalized_model,
            meta={
                "force": force,
                "chunk_size": int(payload.chunk_size),
                "explicit_ids": bool(sanitized_ids is not None),
                "legacy_auto_force": (force and (not bool(payload.force))),
            },
            total=len(sanitized_ids) if sanitized_ids is not None else 0,
        )
    except Exception as e:
        # If another request won the race, the partial unique index on
        # (sr_id) WHERE status IN ('queued','running','paused') will throw.
        if _is_unique_violation(e):
            existing = await run_in_threadpool(run_all_repo.get_active_job_for_sr, sr_id)
            if existing:
                return {
                    "job_id": existing.get("job_id"),
                    "already_running": True,
                    "existing": True,
                    "message_key": "screening.onlyOneJobAtATime",
                    "message": "Only one job can be running at a time",
                    "job": existing,
                }
        raise

    # Mode A (preferred): enqueue chunks immediately when ids provided.
    # Mode B (fallback): enqueue kickoff task that computes eligible ids.
    if sanitized_ids is not None:
        # Preserve paused status if user paused immediately after creating the job.
        if run_all_repo.is_paused(job_id):
            await run_in_threadpool(run_all_repo.set_status, job_id, "paused")
        else:
            await run_in_threadpool(run_all_repo.set_status, job_id, "running")
        await run_in_threadpool(run_all_repo.update_phase, job_id, f"enqueued {len(sanitized_ids)}")

        # Fair scheduling: persist chunks and only enqueue the *next* chunk.
        # This prevents one job from flooding the global queue.
        # Force chunk_size=1 for maximum fairness/responsiveness.
        chunk_size = 1
        chunks = _build_chunks(sanitized_ids, chunk_size)
        await run_in_threadpool(run_all_repo.insert_chunks, job_id, chunks)

        if not await run_in_threadpool(run_all_repo.is_canceled, job_id):
            prefetch = await run_in_threadpool(_compute_run_all_prefetch)
            for _ in range(prefetch):
                next_chunk_id = await run_in_threadpool(
                    run_all_repo.claim_next_todo_chunk,
                    job_id,
                    prefetch=prefetch,
                )
                if next_chunk_id is None:
                    break
                await run_all_chunk.defer_async(job_id=job_id, chunk_id=int(next_chunk_id))

        # Helpful operator logging
        print(
            f"[run-all] queued job_id={job_id} step={step} total={len(sanitized_ids)} chunk_size={chunk_size}",
            flush=True,
        )
    else:
        # Enqueue kickoff task
        await run_all_start.defer_async(job_id=job_id)
        print(
            f"[run-all] queued job_id={job_id} step={step} (server will compute eligible ids)",
            flush=True,
        )

    return {"job_id": job_id, "already_running": False, "existing": False}


@router.get("/run-all/status")
async def run_all_status(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Authz: user must have access to SR.
    sr_id = str(job.get("sr_id"))
    await load_sr_and_check(sr_id, current_user, srdb_service)

    return job


@router.post("/run-all/cancel")
async def run_all_cancel(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sr_id = str(job.get("sr_id"))
    await load_sr_and_check(sr_id, current_user, srdb_service)

    await run_in_threadpool(run_all_repo.mark_canceled, job_id)
    # Best-effort: remove enqueued (todo) chunk jobs from the queue so cancel is fast.
    try:
        deleted = await cancel_enqueued_jobs_for_run_all(job_id)
    except Exception:
        deleted = 0
    return {"status": "canceled", "job_id": job_id, "queue_deleted": deleted}


@router.post("/run-all/pause")
async def run_all_pause(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sr_id = str(job.get("sr_id"))
    await load_sr_and_check(sr_id, current_user, srdb_service)

    # Only pause if running/queued
    st = str(job.get("status") or "").lower()
    if st in {"done", "finished", "failed", "canceled"}:
        return {"status": st, "job_id": job_id}

    await run_in_threadpool(run_all_repo.set_paused, job_id, True)
    return {"status": "paused", "job_id": job_id}


@router.post("/run-all/resume")
async def run_all_resume(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sr_id = str(job.get("sr_id"))
    await load_sr_and_check(sr_id, current_user, srdb_service)

    st = str(job.get("status") or "").lower()
    if st in {"done", "finished", "failed", "canceled"}:
        return {"status": st, "job_id": job_id}

    await run_in_threadpool(run_all_repo.set_paused, job_id, False)
    return {"status": "running", "job_id": job_id}


@router.post("/run-all/dismiss")
async def run_all_dismiss(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Dismiss a sticky terminal job from the UI.

    We keep completed/failed jobs visible using statuses:
    - finished (success)
    - failed

    When the user clicks the icon in the UI, we transition the job to "done"
    which removes it from the /run-all/active list.
    """

    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sr_id = str(job.get("sr_id"))
    await load_sr_and_check(sr_id, current_user, srdb_service)

    st = str(job.get("status") or "").lower()
    if st not in {"finished", "failed"}:
        raise HTTPException(status_code=400, detail="Only finished/failed jobs can be dismissed")

    await run_in_threadpool(run_all_repo.set_status, job_id, "done")
    return {"status": "done", "job_id": job_id}
