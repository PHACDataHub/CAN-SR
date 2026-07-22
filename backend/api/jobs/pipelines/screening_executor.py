from __future__ import annotations

from typing import Any

from fastapi.concurrency import run_in_threadpool

from ...citations import router as citations_router
from ...extract.prompts import PARAMETER_PROMPT_JSON
from ...extract.router import extract_fulltext_from_storage
from ...screen.agentic_utils import build_critical_options
from ...screen.agentic_utils import call_and_parse_agent_response
from ...screen.agentic_utils import resolve_option
from ...screen.prompts import PROMPT_XML_TEMPLATE_FULLTEXT
from ...screen.prompts import PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL
from ...screen.prompts import PROMPT_XML_TEMPLATE_TA
from ...screen.prompts import PROMPT_XML_TEMPLATE_TA_CRITICAL
from ...screen.router import _build_guardrails
from ...screen.router import update_inclusion_decision
from ...services.azure_openai_client import azure_openai_client
from ...services.cit_db_service import cits_dp_service
from ...services.cit_db_service import snake_case
from ...services.cit_db_service import snake_case_column
from ...services.cit_db_service import snake_case_param
from ...services.storage import storage_service
from ..run_all_repo import run_all_repo
from .control import PipelineCanceled
from .control import wait_if_paused


def _should_skip_ai_output(existing_value: Any, *, force: bool) -> bool:
    """Return True if we should skip doing work because output already exists."""
    if force:
        return False
    # Missing output is NULL/empty per planning doc.
    if existing_value is None:
        return False
    if isinstance(existing_value, str) and existing_value.strip() == '':
        return False
    return True


def _eligible_ids(*, sr_id: str, table_name: str, step: str) -> list[int]:
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
    filter_step = ''
    if step == 'l2':
        filter_step = 'l1'
    elif step == 'extract':
        filter_step = 'l2'

    ids = cits_dp_service.list_citation_ids(
        filter_step if filter_step else None, table_name,
    )

    # PDF gating for l2/extract
    if step in ('l2', 'extract'):
        # keep only rows with fulltext_url
        rows = cits_dp_service.get_citations_by_ids(
            ids, table_name, fields=['id', 'fulltext_url'],
        )
        ok = []
        for r in rows:
            try:
                cid = int(r.get('id'))
            except Exception:
                continue
            if r.get('fulltext_url'):
                ok.append(cid)
        return ok
    return ids


async def _run_l1_for_citation(
    *,
    job_id: str,
    sr: dict[str, Any],
    table_name: str,
    citation_id: int,
    model: str | None,
    force: bool,
) -> tuple[int, int, int]:
    """Returns (done, skipped, failed) increments for this citation."""
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    include_cols = cits_dp_service.load_include_columns_from_criteria(sr)
    if not include_cols:
        include_cols = ['title', 'abstract']

    citation_text = citations_router._build_combined_citation_from_row(
        row, include_cols,
    )

    cp = sr.get('criteria_parsed') or sr.get('criteria') or {}
    l1 = cp.get('l1') if isinstance(cp, dict) else None
    questions = (l1 or {}).get('questions') if isinstance(l1, dict) else []
    possible = (l1 or {}).get(
        'possible_answers',
    ) if isinstance(l1, dict) else []
    addinfos = (l1 or {}).get(
        'additional_infos',
    ) if isinstance(l1, dict) else []
    questions = questions if isinstance(questions, list) else []
    possible = possible if isinstance(possible, list) else []
    addinfos = addinfos if isinstance(addinfos, list) else []

    if not questions:
        return (0, 1, 0)

    any_ran = False
    for i, q in enumerate(questions):
        # More responsive pause/cancel: check between questions
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise PipelineCanceled()
        await wait_if_paused(job_id)
        opts = possible[i] if i < len(
            possible,
        ) and isinstance(possible[i], list) else []
        xtra = addinfos[i] if i < len(
            addinfos,
        ) and isinstance(addinfos[i], str) else ''
        col = snake_case_column(q)
        existing = row.get(col)
        if _should_skip_ai_output(existing, force=force):
            continue

        if not azure_openai_client.is_configured():
            raise RuntimeError('Azure OpenAI client not configured')

        # --- Agentic (screening + critical) ---
        # We persist normalized runs to screening_agent_runs so /screen/metrics can compute SR-wide progress.
        # We ALSO persist llm_* JSONB columns for backwards compatibility with the existing UI.
        options_listed = '\n'.join([str(opt) for opt in opts])
        criterion_key = snake_case(q, max_len=56)

        screening_prompt = PROMPT_XML_TEMPLATE_TA.format(
            question=q,
            cit=citation_text,
            options=options_listed,
            xtra=xtra or '',
        )

        async def _call_agent(prompt: str):
            raw = await azure_openai_client.simple_chat(
                user_message=prompt,
                system_prompt=None,
                model=model,
                max_tokens=2000,
                temperature=0.0,
            )
            return str(raw), None

        screening_raw, screening_parsed, _, _ = await call_and_parse_agent_response(
            screening_prompt,
            stage='screening',
            call_llm=_call_agent,
        )
        screening_answer = resolve_option(screening_parsed.answer, opts)

        await run_in_threadpool(
            cits_dp_service.insert_screening_agent_run,
            {
                'sr_id': sr.get('_id') or sr.get('id') or sr.get('sr_id') or '',
                'table_name': table_name,
                'citation_id': int(citation_id),
                'pipeline': 'title_abstract',
                'criterion_key': criterion_key,
                'stage': 'screening',
                'answer': screening_answer,
                'confidence': screening_parsed.confidence,
                'rationale': screening_parsed.rationale,
                'raw_response': str(screening_raw),
                'guardrails': _build_guardrails(screening_parsed, raw_text=str(screening_raw), stage='screening'),
                'model': model,
                'prompt_version': 'run_all',
                'temperature': 0.0,
            },
        )

        critical_opts = build_critical_options(
            all_options=opts, screening_answer=screening_answer,
        )
        critical_listed = '\n'.join([str(o) for o in critical_opts])
        critical_prompt = PROMPT_XML_TEMPLATE_TA_CRITICAL.format(
            question=q,
            cit=citation_text,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or '',
            # run-all does not currently inject SR-scoped critical prompt additions (done in /screen/*/run)
            critical_additions='(none)',
        )
        critical_raw, critical_parsed, _, _ = await call_and_parse_agent_response(
            critical_prompt,
            stage='critical',
            call_llm=_call_agent,
        )
        critical_answer = resolve_option(critical_parsed.answer, critical_opts)

        await run_in_threadpool(
            cits_dp_service.insert_screening_agent_run,
            {
                'sr_id': sr.get('_id') or sr.get('id') or sr.get('sr_id') or '',
                'table_name': table_name,
                'citation_id': int(citation_id),
                'pipeline': 'title_abstract',
                'criterion_key': criterion_key,
                'stage': 'critical',
                'answer': critical_answer,
                'confidence': critical_parsed.confidence,
                'rationale': '',
                'raw_response': str(critical_raw),
                'guardrails': _build_guardrails(critical_parsed, raw_text=str(critical_raw), stage='critical'),
                'model': model,
                'prompt_version': 'run_all',
                'temperature': 0.0,
            },
        )

        classification_json = {
            'selected': screening_answer,
            'explanation': screening_parsed.rationale or '',
            'confidence': screening_parsed.confidence if screening_parsed.confidence is not None else 0.0,
            # Evidence fields parsed from the XML response (fulltext prompt returns these)
            'evidence_sentences': screening_parsed.evidence_sentences or [],
            'evidence_tables': screening_parsed.evidence_tables or [],
            'evidence_figures': screening_parsed.evidence_figures or [],
            'llm_raw': str(screening_raw),
            'critical': {
                'selected': critical_answer,
                'confidence': critical_parsed.confidence,
                'llm_raw': str(critical_raw),
            },
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, classification_json, table_name)

        # Best-effort autofill human_ if empty
        try:
            core = snake_case(q, max_len=56)
            human_col = f"human_{core}" if core else 'human_col'
            human_payload = {
                **classification_json,
                'autofilled': True, 'source': 'llm',
            }
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
        await update_inclusion_decision(sr, citation_id, 'l1', 'llm')
    except Exception:
        pass

    if any_ran:
        return (1, 0, 0)
    return (0, 1, 0)


async def _ensure_fulltext_if_needed(
    *,
    sr_id: str,
    citation_id: int,
    current_user: dict[str, Any],
    table_name: str,
    force: bool,
) -> bool:
    """Ensure fulltext artifacts exist. Returns True if available after this call."""
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return False
    if not row.get('fulltext_url'):
        return False

    # If force is false and fulltext already extracted with matching md5, endpoint is idempotent.
    # If force is true, we still rely on md5 short-circuit; we are not forcing a redo of fulltext extraction
    # because that is expensive and should be driven by PDF change.
    try:
        # type: ignore
        await extract_fulltext_from_storage(sr_id, citation_id, current_user=current_user)
    except Exception:
        # It's okay if DI/grobid fails; L2/extract depends on fulltext text though.
        row2 = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
        return bool(row2 and row2.get('fulltext'))
    row3 = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    return bool(row3 and row3.get('fulltext'))


async def _run_l2_for_citation(
    *,
    job_id: str,
    sr: dict[str, Any],
    table_name: str,
    sr_id: str,
    citation_id: int,
    model: str | None,
    force: bool,
) -> tuple[int, int, int]:
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row or not row.get('fulltext_url'):
        return (0, 1, 0)

    # fake current_user for storage service paths (it only uses id in upload; extract reads by path)
    current_user = {'id': 'system', 'email': 'system'}
    await wait_if_paused(job_id)
    ok = await _ensure_fulltext_if_needed(sr_id=sr_id, citation_id=citation_id, current_user=current_user, table_name=table_name, force=force)
    if not ok:
        return (0, 1, 0)

    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    # L2 fulltext screening applies BOTH L1 + L2 criteria.
    cp = sr.get('criteria_parsed') or sr.get('criteria') or {}
    l1 = cp.get('l1') if isinstance(cp, dict) else None
    l2 = cp.get('l2') if isinstance(cp, dict) else None

    l1_questions = (l1 or {}).get('questions') if isinstance(l1, dict) else []
    l2_questions = (l2 or {}).get('questions') if isinstance(l2, dict) else []
    l1_possible = (l1 or {}).get(
        'possible_answers',
    ) if isinstance(l1, dict) else []
    l2_possible = (l2 or {}).get(
        'possible_answers',
    ) if isinstance(l2, dict) else []
    l1_addinfos = (l1 or {}).get(
        'additional_infos',
    ) if isinstance(l1, dict) else []
    l2_addinfos = (l2 or {}).get(
        'additional_infos',
    ) if isinstance(l2, dict) else []

    l1_questions = l1_questions if isinstance(l1_questions, list) else []
    l2_questions = l2_questions if isinstance(l2_questions, list) else []
    l1_possible = l1_possible if isinstance(l1_possible, list) else []
    l2_possible = l2_possible if isinstance(l2_possible, list) else []
    l1_addinfos = l1_addinfos if isinstance(l1_addinfos, list) else []
    l2_addinfos = l2_addinfos if isinstance(l2_addinfos, list) else []

    merged: list[tuple[str, str, int]] = []  # (question, source_step, idx)
    seen_q: set[str] = set()
    for idx, q in enumerate(l1_questions):
        if not isinstance(q, str) or not q.strip() or q in seen_q:
            continue
        seen_q.add(q)
        merged.append((q, 'l1', idx))
    for idx, q in enumerate(l2_questions):
        if not isinstance(q, str) or not q.strip() or q in seen_q:
            continue
        seen_q.add(q)
        merged.append((q, 'l2', idx))

    if not merged:
        return (0, 1, 0)

    include_cols = cits_dp_service.load_include_columns_from_criteria(sr) or [
        'title', 'abstract',
    ]
    citation_text = citations_router._build_combined_citation_from_row(
        row, include_cols,
    )
    fulltext = row.get('fulltext') or citation_text

    # Tables/Figures context from row
    import json

    tables_md_lines: list[str] = []
    figures_lines: list[str] = []
    images: list[tuple[bytes, str]] = []

    ft_tables = row.get('fulltext_tables')
    if isinstance(ft_tables, str):
        try:
            ft_tables = json.loads(ft_tables)
        except Exception:
            ft_tables = None
    if isinstance(ft_tables, list):
        for item in ft_tables:
            if not isinstance(item, dict):
                continue
            idx = item.get('index')
            blob_addr = item.get('blob_address')
            caption = item.get('caption')
            if not idx or not blob_addr:
                continue
            try:
                md_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                md_txt = md_bytes.decode('utf-8', errors='replace')
                header = f"Table [T{idx}]" + \
                    (f" caption: {caption}" if caption else '')
                tables_md_lines.extend([header, md_txt, ''])
            except Exception:
                continue

    ft_figs = row.get('fulltext_figures')
    if isinstance(ft_figs, str):
        try:
            ft_figs = json.loads(ft_figs)
        except Exception:
            ft_figs = None
    if isinstance(ft_figs, list):
        for item in ft_figs:
            if not isinstance(item, dict):
                continue
            idx = item.get('index')
            blob_addr = item.get('blob_address')
            caption = item.get('caption')
            if not idx or not blob_addr:
                continue
            figures_lines.append(
                f"Figure [F{idx}] caption: {caption or '(no caption)'} (see attached image F{idx})",
            )
            try:
                img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                if img_bytes:
                    images.append((img_bytes, 'image/png'))
            except Exception:
                continue

    any_ran = False
    for q, source_step, idx in merged:
        # More responsive pause/cancel: check between questions
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise PipelineCanceled()
        await wait_if_paused(job_id)
        if source_step == 'l1':
            opts = l1_possible[idx] if idx < len(
                l1_possible,
            ) and isinstance(l1_possible[idx], list) else []
            xtra = l1_addinfos[idx] if idx < len(
                l1_addinfos,
            ) and isinstance(l1_addinfos[idx], str) else ''
        else:
            opts = l2_possible[idx] if idx < len(
                l2_possible,
            ) and isinstance(l2_possible[idx], list) else []
            xtra = l2_addinfos[idx] if idx < len(
                l2_addinfos,
            ) and isinstance(l2_addinfos[idx], str) else ''
        col = snake_case_column(q)
        existing = row.get(col)
        if _should_skip_ai_output(existing, force=force):
            continue

        # --- Agentic (screening + critical) ---
        options_listed = '\n'.join([str(opt) for opt in opts])
        criterion_key = snake_case(q, max_len=56)

        screening_prompt = PROMPT_XML_TEMPLATE_FULLTEXT.format(
            question=q,
            options=options_listed,
            xtra=xtra or '',
            fulltext=fulltext,
            tables='\n'.join(tables_md_lines) if tables_md_lines else '(none)',
            figures='\n'.join(figures_lines) if figures_lines else '(none)',
        )

        async def _call_agent(prompt: str):
            if images:
                raw = await azure_openai_client.multimodal_chat(
                    user_text=prompt,
                    images=images,
                    system_prompt=None,
                    model=model,
                    max_tokens=2000,
                    temperature=0.0,
                )
            else:
                raw = await azure_openai_client.simple_chat(
                    user_message=prompt,
                    system_prompt=None,
                    model=model,
                    max_tokens=2000,
                    temperature=0.0,
                )
            return str(raw), None

        screening_raw, screening_parsed, _, _ = await call_and_parse_agent_response(
            screening_prompt,
            stage='screening',
            call_llm=_call_agent,
        )
        screening_answer = resolve_option(screening_parsed.answer, opts)

        await run_in_threadpool(
            cits_dp_service.insert_screening_agent_run,
            {
                'sr_id': sr.get('_id') or sr.get('id') or sr.get('sr_id') or '',
                'table_name': table_name,
                'citation_id': int(citation_id),
                'pipeline': 'fulltext',
                'criterion_key': criterion_key,
                'stage': 'screening',
                'answer': screening_answer,
                'confidence': screening_parsed.confidence,
                'rationale': screening_parsed.rationale,
                'raw_response': str(screening_raw),
                'guardrails': _build_guardrails(screening_parsed, raw_text=str(screening_raw), stage='screening'),
                'model': model,
                'prompt_version': 'run_all',
                'temperature': 0.0,
            },
        )

        critical_opts = build_critical_options(
            all_options=opts, screening_answer=screening_answer,
        )
        critical_listed = '\n'.join([str(o) for o in critical_opts])
        critical_prompt = PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL.format(
            question=q,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or '',
            critical_additions='(none)',
            fulltext=fulltext,
            tables='\n'.join(tables_md_lines) if tables_md_lines else '(none)',
            figures='\n'.join(figures_lines) if figures_lines else '(none)',
        )
        critical_raw, critical_parsed, _, _ = await call_and_parse_agent_response(
            critical_prompt,
            stage='critical',
            call_llm=_call_agent,
        )
        critical_answer = resolve_option(critical_parsed.answer, critical_opts)

        await run_in_threadpool(
            cits_dp_service.insert_screening_agent_run,
            {
                'sr_id': sr.get('_id') or sr.get('id') or sr.get('sr_id') or '',
                'table_name': table_name,
                'citation_id': int(citation_id),
                'pipeline': 'fulltext',
                'criterion_key': criterion_key,
                'stage': 'critical',
                'answer': critical_answer,
                'confidence': critical_parsed.confidence,
                'rationale': '',
                'raw_response': str(critical_raw),
                'guardrails': _build_guardrails(critical_parsed, raw_text=str(critical_raw), stage='critical'),
                'model': model,
                'prompt_version': 'run_all',
                'temperature': 0.0,
            },
        )

        classification_json = {
            'selected': screening_answer,
            'explanation': screening_parsed.rationale or '',
            'confidence': screening_parsed.confidence if screening_parsed.confidence is not None else 0.0,
            # Evidence fields parsed from the XML response (fulltext prompt returns these)
            'evidence_sentences': screening_parsed.evidence_sentences or [],
            'evidence_tables': screening_parsed.evidence_tables or [],
            'evidence_figures': screening_parsed.evidence_figures or [],
            'llm_raw': str(screening_raw),
            'critical': {
                'selected': critical_answer,
                'confidence': critical_parsed.confidence,
                'llm_raw': str(critical_raw),
            },
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, classification_json, table_name)

        # Best-effort autofill human
        try:
            core = snake_case(q, max_len=56)
            human_col = f"human_{core}" if core else 'human_col'
            human_payload = {
                **classification_json,
                'autofilled': True, 'source': 'llm',
            }
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
        await update_inclusion_decision(sr, citation_id, 'l2', 'llm')
    except Exception:
        pass

    if any_ran:
        return (1, 0, 0)
    return (0, 1, 0)


async def _run_extract_for_citation(
    *,
    job_id: str,
    sr: dict[str, Any],
    table_name: str,
    sr_id: str,
    citation_id: int,
    model: str | None,
    force: bool,
) -> tuple[int, int, int]:
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row or not row.get('fulltext_url'):
        return (0, 1, 0)

    current_user = {'id': 'system', 'email': 'system'}
    await wait_if_paused(job_id)
    ok = await _ensure_fulltext_if_needed(sr_id=sr_id, citation_id=citation_id, current_user=current_user, table_name=table_name, force=force)
    if not ok:
        return (0, 1, 0)

    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        return (0, 0, 1)

    cp = sr.get('criteria_parsed') or sr.get('criteria') or {}
    params = cp.get('parameters') if isinstance(cp, dict) else None
    categories = (params or {}).get(
        'categories',
    ) if isinstance(params, dict) else []
    possible = (params or {}).get(
        'possible_parameters',
    ) if isinstance(params, dict) else []
    descs = (params or {}).get(
        'descriptions',
    ) if isinstance(params, dict) else []
    categories = categories if isinstance(categories, list) else []
    possible = possible if isinstance(possible, list) else []
    descs = descs if isinstance(descs, list) else []

    params_flat: list[tuple[str, str]] = []
    for i, _cat in enumerate(categories):
        arr = possible[i] if i < len(possible) and isinstance(
            possible[i], list,
        ) else []
        darr = descs[i] if i < len(
            descs,
        ) and isinstance(descs[i], list) else []
        for j, p in enumerate(arr):
            name = str(p).strip() if p is not None else ''
            if not name:
                continue
            d = ''
            if j < len(darr):
                d = str(darr[j])
                d = d.replace('<desc>', '').replace('</desc>', '')
            params_flat.append((name, d or name))

    if not params_flat:
        return (0, 1, 0)

    # Build tables/figures context similarly to extract endpoint
    import json

    tables_text = '(none)'
    figures_text = '(none)'
    images: list[tuple[bytes, str]] = []

    ft_tables = row.get('fulltext_tables')
    if isinstance(ft_tables, str):
        try:
            ft_tables = json.loads(ft_tables)
        except Exception:
            ft_tables = None
    if isinstance(ft_tables, list):
        lines: list[str] = []
        for item in ft_tables:
            if not isinstance(item, dict):
                continue
            idx = item.get('index')
            blob_addr = item.get('blob_address')
            caption = item.get('caption')
            if not idx or not blob_addr:
                continue
            try:
                md_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                md_txt = md_bytes.decode('utf-8', errors='replace')
                header = f"Table [T{idx}]" + \
                    (f" caption: {caption}" if caption else '')
                lines.extend([header, md_txt, ''])
            except Exception:
                continue
        tables_text = '\n'.join(lines) if lines else '(none)'

    ft_figs = row.get('fulltext_figures')
    if isinstance(ft_figs, str):
        try:
            ft_figs = json.loads(ft_figs)
        except Exception:
            ft_figs = None
    if isinstance(ft_figs, list):
        flines: list[str] = []
        for item in ft_figs:
            if not isinstance(item, dict):
                continue
            idx = item.get('index')
            blob_addr = item.get('blob_address')
            caption = item.get('caption')
            if not idx or not blob_addr:
                continue
            flines.append(
                f"Figure [F{idx}] caption: {caption or '(no caption)'} (see attached image F{idx})",
            )
            try:
                img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                if img_bytes:
                    images.append((img_bytes, 'image/png'))
            except Exception:
                continue
        figures_text = '\n'.join(flines) if flines else '(none)'

    fulltext = row.get('fulltext')
    if not fulltext:
        return (0, 1, 0)

    any_ran = False
    import json as _json
    import re as _re

    def _extract_json_object(text: str) -> str | None:
        t = text.strip()
        if t.startswith('```'):
            t = _re.sub(r'^```[a-zA-Z0-9_-]*\s*', '', t)
            t = _re.sub(r'\s*```$', '', t)
        start = t.find('{')
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(t)):
            ch = t[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return t[start: i + 1]
        return None

    for name, desc in params_flat:
        # More responsive pause/cancel: check between parameters
        if await run_in_threadpool(run_all_repo.is_canceled, job_id):
            raise PipelineCanceled()
        await wait_if_paused(job_id)
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
            raise RuntimeError('LLM response not valid JSON')

        stored = {
            'found': bool(parsed.get('found')),
            'value': parsed.get('value'),
            'explanation': parsed.get('explanation') or '',
            'evidence_sentences': parsed.get('evidence_sentences') or [],
            'evidence_tables': parsed.get('evidence_tables') or [],
            'evidence_figures': parsed.get('evidence_figures') or [],
            'llm_raw': str(llm_response)[:4000],
        }

        await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col, stored, table_name)

        # best-effort autofill human_param
        try:
            human_col = col.replace('llm_param_', 'human_param_', 1)
            human_payload = {**stored, 'autofilled': True, 'source': 'llm'}
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
