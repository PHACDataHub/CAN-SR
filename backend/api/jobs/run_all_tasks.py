from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi.concurrency import run_in_threadpool

from .procrastinate_app import PROCRASTINATE_APP
from .run_all_repo import run_all_repo
from .procrastinate_app import worker_concurrency
from ..services.sr_db_service import srdb_service
from ..services.cit_db_service import cits_dp_service, snake_case_column, snake_case_param, snake_case
from ..citations import router as citations_router
from ..services.azure_openai_client import azure_openai_client
from ..services.storage import storage_service
from ..extract.router import extract_fulltext_from_storage
from ..screen.router import update_inclusion_decision
from ..screen.prompts import PROMPT_JSON_TEMPLATE, PROMPT_JSON_TEMPLATE_FULLTEXT
from ..extract.prompts import PARAMETER_PROMPT_JSON


def _compute_run_all_prefetch() -> int:
    """Compute fair-share prefetch.

    W = Procrastinate worker concurrency.
    J = number of active run-all jobs.
    """
    w = int(worker_concurrency() or 1)
    try:
        j = int(run_all_repo.count_active_jobs() or 0)
    except Exception:
        j = 0
    j = max(1, j)
    pf = max(1, w // j)
    return min(20, pf)


class RunAllCanceled(Exception):
    """Raised to cooperatively abort a running run-all job."""


async def _wait_if_paused(job_id: str) -> None:
    """Cooperative pause: wait until status != paused or job canceled."""
    while True:
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise RunAllCanceled()
        if not await run_in_threadpool(run_all_repo.is_paused, job_id):
            return
        await asyncio.sleep(0.5)


def _should_skip_ai_output(existing_value: Any, *, force: bool) -> bool:
    """Return True if we should skip doing work because output already exists."""
    if force:
        return False
    # Missing output is NULL/empty per planning doc.
    if existing_value is None:
        return False
    if isinstance(existing_value, str) and existing_value.strip() == "":
        return False
    return True


async def _load_sr_and_table(sr_id: str) -> tuple[Dict[str, Any], str]:
    # Use srdb_service directly (no auth in worker). The start endpoint already authorizes.
    sr = await run_in_threadpool(srdb_service.get_systematic_review, sr_id, True)
    if not sr:
        raise RuntimeError(f"SR not found: {sr_id}")
    screening = sr.get("screening_db") or {}
    table_name = screening.get("table_name") or "citations"
    return sr, table_name


def _eligible_ids(*, sr_id: str, table_name: str, step: str) -> List[int]:
    """Return eligible citation ids for server-computed kickoff mode.

    IMPORTANT: This path is used only when the UI does NOT provide explicit IDs.
    When the UI provides IDs, the UI-side filters (l2 uses filter=l1, extract uses
    filter=l2) are authoritative.

    Requirement alignment:
    - l1: all citations
    - l2: only citations passing the l1 screen filter
    - extract: only citations passing the l2 screen filter
    - l2/extract additionally require an uploaded PDF/fulltext (fulltext_url)
    """

    # Apply filter semantics
    filter_step = ""
    if step == "l2":
        filter_step = "l1"
    elif step == "extract":
        filter_step = "l2"

    ids = cits_dp_service.list_citation_ids(filter_step if filter_step else None, table_name)

    # PDF gating for l2/extract
    if step in ("l2", "extract"):
        # keep only rows with fulltext_url
        rows = cits_dp_service.get_citations_by_ids(ids, table_name, fields=["id", "fulltext_url"])
        ok = []
        for r in rows:
            try:
                cid = int(r.get("id"))
            except Exception:
                continue
            if r.get("fulltext_url"):
                ok.append(cid)
        return ok
    return ids


async def _run_l1_for_citation(
    *,
    job_id: str,
    sr: Dict[str, Any],
    table_name: str,
    citation_id: int,
    model: Optional[str],
    force: bool,
) -> tuple[int, int, int]:
    """Returns (done, skipped, failed) increments for this citation."""
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    include_cols = cits_dp_service.load_include_columns_from_criteria(sr)
    if not include_cols:
        include_cols = ["title", "abstract"]

    citation_text = citations_router._build_combined_citation_from_row(row, include_cols)

    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    l1 = cp.get("l1") if isinstance(cp, dict) else None
    questions = (l1 or {}).get("questions") if isinstance(l1, dict) else []
    possible = (l1 or {}).get("possible_answers") if isinstance(l1, dict) else []
    addinfos = (l1 or {}).get("additional_infos") if isinstance(l1, dict) else []
    questions = questions if isinstance(questions, list) else []
    possible = possible if isinstance(possible, list) else []
    addinfos = addinfos if isinstance(addinfos, list) else []

    if not questions:
        return (0, 1, 0)

    any_ran = False
    for i, q in enumerate(questions):
        # More responsive pause/cancel: check between questions
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise RunAllCanceled()
        await _wait_if_paused(job_id)
        opts = possible[i] if i < len(possible) and isinstance(possible[i], list) else []
        xtra = addinfos[i] if i < len(addinfos) and isinstance(addinfos[i], str) else ""
        col = snake_case_column(q)
        existing = row.get(col)
        if _should_skip_ai_output(existing, force=force):
            continue

        if not azure_openai_client.is_configured():
            raise RuntimeError("Azure OpenAI client not configured")

        options_listed = "\n".join([f"{j}. {opt}" for j, opt in enumerate(opts)])
        prompt = PROMPT_JSON_TEMPLATE.format(question=q, cit=citation_text, options=options_listed, xtra=xtra)
        llm_response = await azure_openai_client.simple_chat(
            user_message=prompt,
            system_prompt=None,
            model=model,
            max_tokens=2000,
            temperature=0.0,
        )

        import json

        parsed = json.loads(llm_response)
        selected_value = str(parsed.get("selected", "")).strip()
        resolved_selected = f"None of the above - {selected_value}"
        for opt in opts:
            if opt.lower() in selected_value.lower():
                resolved_selected = opt
                break

        classification_json = {
            "selected": resolved_selected,
            "explanation": parsed.get("explanation") or parsed.get("reason") or parsed.get("explain") or "",
            "confidence": float(parsed.get("confidence") or 0.0) if str(parsed.get("confidence") or "").strip() else 0.0,
            "evidence_sentences": parsed.get("evidence_sentences") or [],
            "evidence_tables": parsed.get("evidence_tables") or [],
            "evidence_figures": parsed.get("evidence_figures") or [],
            "llm_raw": llm_response,
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, classification_json, table_name)

        # Best-effort autofill human_ if empty
        try:
            core = snake_case(q, max_len=56)
            human_col = f"human_{core}" if core else "human_col"
            human_payload = {**classification_json, "autofilled": True, "source": "llm"}
            await run_in_threadpool(
                cits_dp_service.copy_jsonb_if_empty,
                citation_id,
                col,
                human_col,
                human_payload,
                table_name,
            )
        except Exception:
            pass

        any_ran = True

    # Update derived decisions (uses fresh row inside)
    try:
        await update_inclusion_decision(sr, citation_id, "l1", "llm")
    except Exception:
        pass

    if any_ran:
        return (1, 0, 0)
    return (0, 1, 0)


async def _ensure_fulltext_if_needed(
    *,
    sr_id: str,
    citation_id: int,
    current_user: Dict[str, Any],
    table_name: str,
    force: bool,
) -> bool:
    """Ensure fulltext artifacts exist. Returns True if available after this call."""
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return False
    if not row.get("fulltext_url"):
        return False

    # If force is false and fulltext already extracted with matching md5, endpoint is idempotent.
    # If force is true, we still rely on md5 short-circuit; we are not forcing a redo of fulltext extraction
    # because that is expensive and should be driven by PDF change.
    try:
        await extract_fulltext_from_storage(sr_id, citation_id, current_user=current_user)  # type: ignore
    except Exception:
        # It's okay if DI/grobid fails; L2/extract depends on fulltext text though.
        row2 = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
        return bool(row2 and row2.get("fulltext"))
    row3 = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    return bool(row3 and row3.get("fulltext"))


async def _run_l2_for_citation(
    *,
    job_id: str,
    sr: Dict[str, Any],
    table_name: str,
    sr_id: str,
    citation_id: int,
    model: Optional[str],
    force: bool,
) -> tuple[int, int, int]:
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row or not row.get("fulltext_url"):
        return (0, 1, 0)

    # fake current_user for storage service paths (it only uses id in upload; extract reads by path)
    current_user = {"id": "system", "email": "system"}
    await _wait_if_paused(job_id)
    ok = await _ensure_fulltext_if_needed(sr_id=sr_id, citation_id=citation_id, current_user=current_user, table_name=table_name, force=force)
    if not ok:
        return (0, 1, 0)

    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    l2 = cp.get("l2") if isinstance(cp, dict) else None
    questions = (l2 or {}).get("questions") if isinstance(l2, dict) else []
    possible = (l2 or {}).get("possible_answers") if isinstance(l2, dict) else []
    addinfos = (l2 or {}).get("additional_infos") if isinstance(l2, dict) else []
    questions = questions if isinstance(questions, list) else []
    possible = possible if isinstance(possible, list) else []
    addinfos = addinfos if isinstance(addinfos, list) else []
    if not questions:
        return (0, 1, 0)

    include_cols = cits_dp_service.load_include_columns_from_criteria(sr) or ["title", "abstract"]
    citation_text = citations_router._build_combined_citation_from_row(row, include_cols)
    fulltext = row.get("fulltext") or citation_text

    # Tables/Figures context from row
    import json

    tables_md_lines: List[str] = []
    figures_lines: List[str] = []
    images: List[tuple[bytes, str]] = []

    ft_tables = row.get("fulltext_tables")
    if isinstance(ft_tables, str):
        try:
            ft_tables = json.loads(ft_tables)
        except Exception:
            ft_tables = None
    if isinstance(ft_tables, list):
        for item in ft_tables:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            blob_addr = item.get("blob_address")
            caption = item.get("caption")
            if not idx or not blob_addr:
                continue
            try:
                md_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                md_txt = md_bytes.decode("utf-8", errors="replace")
                header = f"Table [T{idx}]" + (f" caption: {caption}" if caption else "")
                tables_md_lines.extend([header, md_txt, ""])
            except Exception:
                continue

    ft_figs = row.get("fulltext_figures")
    if isinstance(ft_figs, str):
        try:
            ft_figs = json.loads(ft_figs)
        except Exception:
            ft_figs = None
    if isinstance(ft_figs, list):
        for item in ft_figs:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            blob_addr = item.get("blob_address")
            caption = item.get("caption")
            if not idx or not blob_addr:
                continue
            figures_lines.append(f"Figure [F{idx}] caption: {caption or '(no caption)'} (see attached image F{idx})")
            try:
                img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                if img_bytes:
                    images.append((img_bytes, "image/png"))
            except Exception:
                continue

    any_ran = False
    for i, q in enumerate(questions):
        # More responsive pause/cancel: check between questions
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise RunAllCanceled()
        await _wait_if_paused(job_id)
        opts = possible[i] if i < len(possible) and isinstance(possible[i], list) else []
        xtra = addinfos[i] if i < len(addinfos) and isinstance(addinfos[i], str) else ""
        col = snake_case_column(q)
        existing = row.get(col)
        if _should_skip_ai_output(existing, force=force):
            continue

        options_listed = "\n".join([f"{j}. {opt}" for j, opt in enumerate(opts)])
        prompt = PROMPT_JSON_TEMPLATE_FULLTEXT.format(
            question=q,
            options=options_listed,
            xtra=xtra,
            fulltext=fulltext,
            tables="\n".join(tables_md_lines) if tables_md_lines else "(none)",
            figures="\n".join(figures_lines) if figures_lines else "(none)",
        )

        if images:
            llm_response = await azure_openai_client.multimodal_chat(
                user_text=prompt,
                images=images,
                system_prompt=None,
                model=model,
                max_tokens=2000,
                temperature=0.0,
            )
        else:
            llm_response = await azure_openai_client.simple_chat(
                user_message=prompt,
                system_prompt=None,
                model=model,
                max_tokens=2000,
                temperature=0.0,
            )

        parsed = json.loads(llm_response)
        selected_value = str(parsed.get("selected", "")).strip()
        resolved_selected = f"None of the above - {selected_value}"
        for opt in opts:
            if opt.lower() in selected_value.lower():
                resolved_selected = opt
                break

        classification_json = {
            "selected": resolved_selected,
            "explanation": parsed.get("explanation") or parsed.get("reason") or parsed.get("explain") or "",
            "confidence": float(parsed.get("confidence") or 0.0) if str(parsed.get("confidence") or "").strip() else 0.0,
            "evidence_sentences": parsed.get("evidence_sentences") or [],
            "evidence_tables": parsed.get("evidence_tables") or [],
            "evidence_figures": parsed.get("evidence_figures") or [],
            "llm_raw": llm_response,
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, classification_json, table_name)

        # Best-effort autofill human
        try:
            core = snake_case(q, max_len=56)
            human_col = f"human_{core}" if core else "human_col"
            human_payload = {**classification_json, "autofilled": True, "source": "llm"}
            await run_in_threadpool(
                cits_dp_service.copy_jsonb_if_empty,
                citation_id,
                col,
                human_col,
                human_payload,
                table_name,
            )
        except Exception:
            pass

        any_ran = True

    try:
        await update_inclusion_decision(sr, citation_id, "l2", "llm")
    except Exception:
        pass

    if any_ran:
        return (1, 0, 0)
    return (0, 1, 0)


async def _run_extract_for_citation(
    *,
    job_id: str,
    sr: Dict[str, Any],
    table_name: str,
    sr_id: str,
    citation_id: int,
    model: Optional[str],
    force: bool,
) -> tuple[int, int, int]:
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row or not row.get("fulltext_url"):
        return (0, 1, 0)

    current_user = {"id": "system", "email": "system"}
    await _wait_if_paused(job_id)
    ok = await _ensure_fulltext_if_needed(sr_id=sr_id, citation_id=citation_id, current_user=current_user, table_name=table_name, force=force)
    if not ok:
        return (0, 1, 0)

    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    params = cp.get("parameters") if isinstance(cp, dict) else None
    categories = (params or {}).get("categories") if isinstance(params, dict) else []
    possible = (params or {}).get("possible_parameters") if isinstance(params, dict) else []
    descs = (params or {}).get("descriptions") if isinstance(params, dict) else []
    categories = categories if isinstance(categories, list) else []
    possible = possible if isinstance(possible, list) else []
    descs = descs if isinstance(descs, list) else []

    params_flat: List[tuple[str, str]] = []
    for i, _cat in enumerate(categories):
        arr = possible[i] if i < len(possible) and isinstance(possible[i], list) else []
        darr = descs[i] if i < len(descs) and isinstance(descs[i], list) else []
        for j, p in enumerate(arr):
            name = str(p).strip() if p is not None else ""
            if not name:
                continue
            d = ""
            if j < len(darr):
                d = str(darr[j])
                d = d.replace("<desc>", "").replace("</desc>", "")
            params_flat.append((name, d or name))

    if not params_flat:
        return (0, 1, 0)

    # Build tables/figures context similarly to extract endpoint
    import json

    tables_text = "(none)"
    figures_text = "(none)"
    images: List[tuple[bytes, str]] = []

    ft_tables = row.get("fulltext_tables")
    if isinstance(ft_tables, str):
        try:
            ft_tables = json.loads(ft_tables)
        except Exception:
            ft_tables = None
    if isinstance(ft_tables, list):
        lines: List[str] = []
        for item in ft_tables:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            blob_addr = item.get("blob_address")
            caption = item.get("caption")
            if not idx or not blob_addr:
                continue
            try:
                md_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                md_txt = md_bytes.decode("utf-8", errors="replace")
                header = f"Table [T{idx}]" + (f" caption: {caption}" if caption else "")
                lines.extend([header, md_txt, ""])
            except Exception:
                continue
        tables_text = "\n".join(lines) if lines else "(none)"

    ft_figs = row.get("fulltext_figures")
    if isinstance(ft_figs, str):
        try:
            ft_figs = json.loads(ft_figs)
        except Exception:
            ft_figs = None
    if isinstance(ft_figs, list):
        flines: List[str] = []
        for item in ft_figs:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            blob_addr = item.get("blob_address")
            caption = item.get("caption")
            if not idx or not blob_addr:
                continue
            flines.append(f"Figure [F{idx}] caption: {caption or '(no caption)'} (see attached image F{idx})")
            try:
                img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                if img_bytes:
                    images.append((img_bytes, "image/png"))
            except Exception:
                continue
        figures_text = "\n".join(flines) if flines else "(none)"

    fulltext = row.get("fulltext")
    if not fulltext:
        return (0, 1, 0)

    any_ran = False
    import json as _json
    import re as _re

    def _extract_json_object(text: str) -> Optional[str]:
        t = text.strip()
        if t.startswith("```"):
            t = _re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
            t = _re.sub(r"\s*```$", "", t)
        start = t.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(t)):
            ch = t[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return t[start : i + 1]
        return None

    for name, desc in params_flat:
        # More responsive pause/cancel: check between parameters
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise RunAllCanceled()
        await _wait_if_paused(job_id)
        col = snake_case_param(name)
        existing = row.get(col)
        if _should_skip_ai_output(existing, force=force):
            continue

        prompt = PARAMETER_PROMPT_JSON.format(
            parameter_name=name,
            parameter_description=desc,
            fulltext=fulltext,
            tables=tables_text,
            figures=figures_text,
        )

        if images:
            llm_response = await azure_openai_client.multimodal_chat(
                user_text=prompt,
                images=images,
                system_prompt=None,
                model=model,
                max_tokens=512,
                temperature=0.0,
            )
        else:
            llm_response = await azure_openai_client.simple_chat(
                user_message=prompt,
                system_prompt=None,
                model=model,
                max_tokens=512,
                temperature=0.0,
            )

        parsed = None
        try:
            parsed = _json.loads(llm_response)
        except Exception:
            maybe = _extract_json_object(llm_response)
            if maybe:
                parsed = _json.loads(maybe)

        if not isinstance(parsed, dict):
            raise RuntimeError("LLM response not valid JSON")

        stored = {
            "found": bool(parsed.get("found")),
            "value": parsed.get("value"),
            "explanation": parsed.get("explanation") or "",
            "evidence_sentences": parsed.get("evidence_sentences") or [],
            "evidence_tables": parsed.get("evidence_tables") or [],
            "evidence_figures": parsed.get("evidence_figures") or [],
            "llm_raw": str(llm_response)[:4000],
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, stored, table_name)

        # best-effort autofill human_param
        try:
            human_col = col.replace("llm_param_", "human_param_", 1)
            human_payload = {**stored, "autofilled": True, "source": "llm"}
            await run_in_threadpool(
                cits_dp_service.copy_jsonb_if_empty,
                citation_id,
                col,
                human_col,
                human_payload,
                table_name,
            )
        except Exception:
            pass

        any_ran = True

    if any_ran:
        return (1, 0, 0)
    return (0, 1, 0)


@PROCRASTINATE_APP.task(queue="default")
async def run_all_start(job_id: str) -> None:
    """Compute eligible IDs and enqueue chunks."""
    try:
        job = await run_in_threadpool(run_all_repo.get_job, job_id)
        if not job:
            return
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            return

        sr_id = str(job.get("sr_id"))
        step = str(job.get("step"))
        # Force chunk_size=1 for maximum fairness/responsiveness.
        # NOTE: meta may store a historical chunk_size from the request, but
        # we intentionally ignore it here.
        chunk_size = 1
        ids = []

        sr, table_name = await _load_sr_and_table(sr_id)
        ids = await run_in_threadpool(_eligible_ids, sr_id=sr_id, table_name=table_name, step=step)
        await run_in_threadpool(run_all_repo.set_total, job_id, len(ids))
        print(f"[run-all] kickoff job_id={job_id} step={step} eligible={len(ids)}", flush=True)

        # If user paused before kickoff, preserve paused status.
        if await run_in_threadpool(run_all_repo.is_paused, job_id):
            await run_in_threadpool(run_all_repo.set_status, job_id, "paused")
        else:
            await run_in_threadpool(run_all_repo.set_status, job_id, "running")
        await run_in_threadpool(run_all_repo.update_phase, job_id, f"enqueued {len(ids)}")

        # Fair scheduling: persist chunks and enqueue only the next chunk.
        chunks = [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]
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

    except Exception as e:
        await run_in_threadpool(run_all_repo.set_status, job_id, "failed", error=str(e))


@PROCRASTINATE_APP.task(queue="default")
async def run_all_chunk(job_id: str, chunk_id: int) -> None:
    """Process a chunk sequentially.

    For fairness across multiple run-all jobs, we only keep a small number of
    chunks in-flight per job (prefetch). Each finished chunk schedules more work
    until the prefetch limit is reached.
    """
    chunk = await run_in_threadpool(run_all_repo.get_chunk, int(chunk_id))
    if not chunk:
        return
    citation_ids = chunk.get("citation_ids") or []
    if not isinstance(citation_ids, list):
        citation_ids = []
    print(
        f"[run-all] chunk_start job_id={job_id} chunk_id={chunk_id} size={len(citation_ids)}",
        flush=True,
    )
    job = await run_in_threadpool(run_all_repo.get_job, job_id)
    if not job:
        return
    if await run_in_threadpool(run_all_repo.is_canceled, job_id):
        return

    sr_id = str(job.get("sr_id"))
    step = str(job.get("step"))
    model = job.get("model")
    meta = job.get("meta") or {}
    force = bool(meta.get("force"))

    sr, table_name = await _load_sr_and_table(sr_id)

    chunk_failed = False
    chunk_error: Optional[str] = None

    for cid in citation_ids:
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            return
        await _wait_if_paused(job_id)
        await run_in_threadpool(run_all_repo.update_phase, job_id, f"citation {cid}")

        try:
            await _wait_if_paused(job_id)
            if step == "l1":
                d, s, f = await _run_l1_for_citation(job_id=job_id, sr=sr, table_name=table_name, citation_id=int(cid), model=model, force=force)
            elif step == "l2":
                d, s, f = await _run_l2_for_citation(job_id=job_id, sr=sr, table_name=table_name, sr_id=sr_id, citation_id=int(cid), model=model, force=force)
            elif step == "extract":
                d, s, f = await _run_extract_for_citation(job_id=job_id, sr=sr, table_name=table_name, sr_id=sr_id, citation_id=int(cid), model=model, force=force)
            else:
                d, s, f = (0, 1, 0)
            await run_in_threadpool(run_all_repo.inc_counts, job_id, done=d, skipped=s, failed=f)
        except RunAllCanceled:
            return
        except Exception as e:
            await run_in_threadpool(run_all_repo.add_error, job_id, citation_id=int(cid), stage=step, error=str(e))
            await run_in_threadpool(run_all_repo.inc_counts, job_id, failed=1)
            chunk_failed = True
            chunk_error = str(e)

    print(
        f"[run-all] chunk_done job_id={job_id} chunk_id={chunk_id} size={len(citation_ids)}",
        flush=True,
    )

    # Mark chunk complete and schedule more work (up to prefetch).
    try:
        if chunk_failed:
            await run_in_threadpool(run_all_repo.mark_chunk_failed, int(chunk_id), error=chunk_error or "chunk had failures")
        else:
            await run_in_threadpool(run_all_repo.mark_chunk_done, int(chunk_id))
    except Exception:
        # non-fatal
        pass

    # If the job is paused/canceled, do not enqueue next chunk yet.
    if await run_in_threadpool(run_all_repo.is_canceled, job_id):
        return
    await _wait_if_paused(job_id)

    try:
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
    except Exception:
        # non-fatal; job will still finish once counts reach total
        pass

    # If all chunks finished, we don't have a built-in counter. For phase 1, we consider
    # job done once done+skipped+failed >= total.
    try:
        job2 = await run_in_threadpool(run_all_repo.get_job, job_id)
        if job2:
            total = int(job2.get("total") or 0)
            done = int(job2.get("done") or 0)
            skipped = int(job2.get("skipped") or 0)
            failed = int(job2.get("failed") or 0)
            if total > 0 and (done + skipped + failed) >= total and not await run_in_threadpool(run_all_repo.is_canceled, job_id):
                await run_in_threadpool(run_all_repo.set_status, job_id, "done")
    except Exception:
        pass
