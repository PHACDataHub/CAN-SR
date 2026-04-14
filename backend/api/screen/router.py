from typing import Any, Dict, List, Optional, Tuple
import json
import re
from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..services.sr_db_service import srdb_service
from ..core.config import settings
from ..core.security import get_current_active_user
from ..services.azure_openai_client import azure_openai_client
from ..services.storage import storage_service

# Import helpers from citations router to fetch citation rows and build combined citations
from ..citations import router as citations_router
from ..core.cit_utils import load_sr_and_check

# Import consolidated Postgres helpers if available (optional)
from ..services.cit_db_service import cits_dp_service, snake_case_column, snake_case
from .prompts import (
    PROMPT_JSON_TEMPLATE,
    PROMPT_JSON_TEMPLATE_FULLTEXT,
    PROMPT_XML_TEMPLATE_TA,
    PROMPT_XML_TEMPLATE_TA_CRITICAL,
    PROMPT_XML_TEMPLATE_FULLTEXT,
    PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL,
)
from .agentic_utils import build_critical_options, parse_agent_xml, resolve_option

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentRunsQueryResponse(BaseModel):
    sr_id: str
    pipeline: str
    citation_ids: List[int]
    runs: List[Dict[str, Any]]


class ScreeningMetricsCriterion(BaseModel):
    criterion_key: str
    label: str
    threshold: float
    total_citations: int
    has_run_count: int
    low_confidence_count: int
    critical_disagreement_count: int
    confident_exclude_count: int
    needs_human_review_count: int


class ScreeningMetricsSummary(BaseModel):
    step: str
    total_citations: int
    validated_all: int
    unvalidated_all: int
    validated_needs_review: int
    unvalidated_needs_review: int
    needs_review_total: int


class ScreeningMetricsResponse(BaseModel):
    sr_id: str
    steps: Dict[str, Any]


def _normalize_int_list(v: Any) -> List[int]:
    if v is None:
        return []
    if not isinstance(v, list):
        return []
    out: List[int] = []
    for item in v:
        if isinstance(item, int):
            out.append(item)
        elif isinstance(item, str):
            try:
                out.append(int(item.strip()))
            except Exception:
                continue
        else:
            continue
    # stable unique
    seen = set()
    uniq: List[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


class ClassifyRequest(BaseModel):
    citation_text: Optional[str] = Field(
        None, description="Optional combined citation text. If omitted the server will build it from the screening DB row."
    )
    include_columns: Optional[List[str]] = Field(
        None, description="If citation_text is omitted, these columns (original CSV headers) will be used to build the combined citation"
    )
    question: str = Field(..., description="L1 criteria question to apply to this citation")
    screening_step: str = Field(..., description="Screening step identifier: 'l1' or 'l2', etc.")
    options: List[str] = Field(..., description="List of possible options (exact strings). The model must pick one.")
    xtra: Optional[str] = Field("", description="Additional context/instructions for the model")
    model: Optional[str] = Field(None, description="Model to use (falls back to default configured model)")
    temperature: Optional[float] = Field(0.0, ge=0.0, le=1.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(2000, ge=1, le=4000, description="Max tokens for LLM response")

class HumanClassifyRequest(BaseModel):
    """
    Request payload for persisting a human-provided L1 screening answer.
    This mirrors the shape of the LLM-based classify payload but accepts a
    direct `selected` value and optional explanation/confidence.
    """
    citation_text: Optional[str] = Field(
        None, description="Optional combined citation text. If omitted the server will build it from the screening DB row."
    )
    include_columns: Optional[List[str]] = Field(
        None, description="If citation_text is omitted, these columns (original CSV headers) will be used to build the combined citation"
    )
    question: str = Field(..., description="L1 criteria question to apply to this citation")
    selected: str = Field(..., description="Human-selected option (string)")
    screening_step: str = Field(..., description="Screening step identifier: 'l1' or 'l2', etc.")
    explanation: Optional[str] = Field("", description="Optional free-text explanation from the human reviewer")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Optional confidence (0.0 - 1.0)")
    reviewer: Optional[str] = Field(None, description="Optional reviewer id or name")


class TitleAbstractRunRequest(BaseModel):
    sr_id: str = Field(..., description="Systematic review id")
    citation_id: int = Field(..., ge=1, description="Citation id (row id in the SR screening table)")
    model: Optional[str] = Field(None, description="Model key/deployment to use")
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    max_tokens: int = Field(1200, ge=64, le=4000)
    prompt_version: Optional[str] = Field("v1", description="Prompt version tag for auditing")


class ValidateStepRequest(BaseModel):
    sr_id: str = Field(..., description="Systematic review id")
    citation_id: int = Field(..., ge=1, description="Citation id (row id in the SR screening table)")
    step: str = Field("l1", description="Validation step: l1|l2|parameters")
    checked: bool = Field(True, description="If true, add/update the current user's validation; if false, remove it")


def _as_validation_list(v: Any) -> List[Dict[str, str]]:
    """Normalize DB values into a list of {user, validated_at} dicts."""

    if v is None:
        return []

    # JSONB may come back as a list already; some deployments may return it as string.
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []

    if not isinstance(v, list):
        return []

    out: List[Dict[str, str]] = []
    for item in v:
        if not isinstance(item, dict):
            continue
        user = item.get("user") or item.get("email") or item.get("validated_by")
        ts = item.get("validated_at") or item.get("timestamp") or item.get("validatedAt")
        if not user:
            continue
        out.append({"user": str(user), "validated_at": str(ts or "")})
    return out


def _dedupe_validations(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep only one entry per user, keeping the latest timestamp lexicographically (ISO8601)."""

    by_user: Dict[str, Dict[str, str]] = {}
    for it in items or []:
        user = str(it.get("user") or "").strip()
        if not user:
            continue
        cur = by_user.get(user)
        if not cur:
            by_user[user] = {"user": user, "validated_at": str(it.get("validated_at") or "")}
            continue
        # Prefer newest timestamp (ISO strings compare in chronological order)
        if str(it.get("validated_at") or "") >= str(cur.get("validated_at") or ""):
            by_user[user] = {"user": user, "validated_at": str(it.get("validated_at") or "")}

    # Return newest-first for nicer UI (most recent first)
    return sorted(by_user.values(), key=lambda x: str(x.get("validated_at") or ""), reverse=True)


def _is_disagreeing_critical_answer(ans: Any) -> bool:
    """Return True if critical stage indicates disagreement.

    Contract: agreement is encoded as "None of the above".
    Any non-empty answer other than that is treated as critical disagreement.
    """

    s = str(ans or "").strip()
    if not s:
        return False
    return s != "None of the above"


def _is_exclude_answer(ans: Any) -> bool:
    """Detect exclude answers by convention: contains '(exclude)' (case-insensitive)."""

    s = str(ans or "")
    return "(exclude)" in s.lower()


def _criterion_key_from_question(question: str) -> str:
    # Keep in sync with the frontend derivation in l2-screen view.
    q = str(question or "")
    try:
        # Prefer shared helper when available.
        return str(snake_case(q, max_len=56))
    except Exception:
        # Fallback: lowercase, non-word -> underscore, collapse underscores.
        s = q.strip().lower()
        s = re.sub(r"[^\w]+", "_", s)
        s = re.sub(r"_+", "_", s)
        s = re.sub(r"^_+|_+$", "", s)
        return s[:56]



class FulltextRunRequest(BaseModel):
    sr_id: str = Field(..., description="Systematic review id")
    citation_id: int = Field(..., ge=1, description="Citation id (row id in the SR screening table)")
    model: Optional[str] = Field(None, description="Model key/deployment to use")
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    max_tokens: int = Field(2000, ge=64, le=4000)
    prompt_version: Optional[str] = Field("v1", description="Prompt version tag for auditing")

    
# _update_sync moved to backend.api.core.postgres.update_jsonb_column
# Use run_in_threadpool(update_jsonb_column, ...) where needed.



@router.post("/{sr_id}/citations/{citation_id}/classify")
async def classify_citation(
    sr_id: str,
    citation_id: int,
    payload: ClassifyRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Classify a citation using an LLM and persist the parsed JSON result into the screening Postgres citations table
    under a dynamically created JSONB column derived from the question text (prefixed with 'llm_').

    This implementation assumes the model returns valid JSON. If parsing fails, a 502 is returned.
    The 'selected' field in the returned JSON is validated against the provided `options`.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Load citation row (needed for l2 fulltext and for building citation_text)
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Build or use provided citation text (fall back to combined title/abstract when not provided)
    citation_text = payload.citation_text or citations_router._build_combined_citation_from_row(row, payload.include_columns)

    # Ensure LLM client is available
    if not azure_openai_client.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Azure OpenAI client is not configured on the server")

    # Prepare prompt (use full-text template for l2, otherwise TA/L1 template)
    options_listed = "\n".join([f"{i}. {opt}" for i, opt in enumerate(payload.options)])
    llm_response: str

    if (payload.screening_step or "").lower() == "l2":
        fulltext = row.get("fulltext") or ""

        # Tables/Figures context from citation row (populated by extract-fulltext)
        tables_md_lines: List[str] = []
        figures_lines: List[str] = []
        images: List[Tuple[bytes, str]] = []

        # Tables: fetch markdown blobs and embed
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
                except Exception:
                    continue
                md_txt = md_bytes.decode("utf-8", errors="replace")
                header = f"Table [T{idx}]" + (f" caption: {caption}" if caption else "")
                tables_md_lines.extend([header, md_txt, ""])

        # Figures: fetch png blobs and attach as images
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
                figures_lines.append(
                    f"Figure [F{idx}] caption: {caption or '(no caption)'} (see attached image F{idx})"
                )
                try:
                    img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                    if img_bytes:
                        images.append((img_bytes, "image/png"))
                except Exception:
                    continue

        prompt = PROMPT_JSON_TEMPLATE_FULLTEXT.format(
            question=payload.question,
            options=options_listed,
            xtra=payload.xtra or "",
            fulltext=fulltext or citation_text,
            tables="\n".join(tables_md_lines) if tables_md_lines else "(none)",
            figures="\n".join(figures_lines) if figures_lines else "(none)",
        )

        # Prefer multimodal when figures are present
        if images:
            llm_response = await azure_openai_client.multimodal_chat(
                user_text=prompt,
                images=images,
                system_prompt=None,
                model=payload.model,
                max_tokens=payload.max_tokens or 2000,
                temperature=payload.temperature or 0.0,
            )
        else:
            llm_response = await azure_openai_client.simple_chat(
                user_message=prompt,
                system_prompt=None,
                model=payload.model,
                max_tokens=payload.max_tokens or 2000,
                temperature=payload.temperature or 0.0,
            )
    else:
        prompt = PROMPT_JSON_TEMPLATE.format(
            question=payload.question,
            cit=citation_text,
            options=options_listed,
            xtra=payload.xtra or "",
        )
        llm_response = await azure_openai_client.simple_chat(
            user_message=prompt,
            system_prompt=None,
            model=payload.model,
            max_tokens=payload.max_tokens or 2000,
            temperature=payload.temperature or 0.0,
        )

    # Parse JSON (assume valid JSON) - try/except only
    logger.info(llm_response)
    try:
        parsed = json.loads(llm_response)
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM response was not valid JSON: {llm_response[:1000]}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM response JSON was not an object: {str(type(parsed))}")

    # Require 'selected' key and validate it is a string
    if "selected" not in parsed:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM JSON missing 'selected' key: {json.dumps(parsed)[:1000]}")
    selected_value = parsed.get("selected")
    if not isinstance(selected_value, str):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM 'selected' must be a string: {str(type(selected_value))}")

    s = selected_value.strip()

    # Direct string match: try exact first, then case-insensitive
    resolved_selected = f"None of the above - {s}"
    for opt in payload.options:
        if opt.lower() in s.lower():
            resolved_selected = opt
            break

    explanation = parsed.get("explanation") or parsed.get("reason") or parsed.get("explain") or ""
    confidence_raw = parsed.get("confidence")

    # Parse confidence
    try:
        confidence = float(confidence_raw)
        confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = 0.0

    evidence = _normalize_int_list(parsed.get("evidence_sentences"))
    evidence_tables = _normalize_int_list(parsed.get("evidence_tables"))
    evidence_figures = _normalize_int_list(parsed.get("evidence_figures"))

    classification_json = {
        "selected": resolved_selected,
        "explanation": explanation,
        "confidence": confidence,
        "evidence_sentences": evidence,
        "evidence_tables": evidence_tables,
        "evidence_figures": evidence_figures,
        "llm_raw": llm_response,  # raw response for audit
    }

    # Persist into Postgres under a dynamic column name derived from question
    col_name = snake_case_column(payload.question)

    # Human mirror column name (same slug as llm_, but prefixed human_)
    try:
        col_core_h = snake_case(payload.question, max_len=56) if snake_case else ""
    except Exception:
        col_core_h = ""
    human_col_name = f"human_{col_core_h}" if col_core_h else "human_col"

    try:
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col_name, classification_json, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    # Auto-fill human_* from llm_* if missing (never overwrite)
    try:
        human_payload = {
            **classification_json,
            "autofilled": True,
            "source": "llm",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        await run_in_threadpool(
            cits_dp_service.copy_jsonb_if_empty,
            citation_id,
            col_name,
            human_col_name,
            human_payload,
            table_name,
        )
    except Exception:
        # best-effort
        pass
    
    await update_inclusion_decision(sr, citation_id, payload.screening_step, "llm")

    return {"status": "success", "sr_id": sr_id, "citation_id": citation_id, "column": col_name, "classification": classification_json}


@router.post("/{sr_id}/citations/{citation_id}/human_classify")
async def human_classify_citation(
    sr_id: str,
    citation_id: int,
    payload: HumanClassifyRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Persist a human-provided answer for an L1 screening question into the screening
    Postgres citations table under a dynamically created JSONB column derived from the question text.
    The column name is prefixed with 'human_' to distinguish from automated classifications.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Ensure citation exists and optionally build combined citation text
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    citation_text = payload.citation_text
    confidence = payload.confidence

    classification_json = {
        "selected": payload.selected,
        "explanation": payload.explanation or "",
        "confidence": confidence if confidence is not None else None,
        "human": True,
        "reviewer": payload.reviewer,
        "citation_text": (citation_text or ""),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Persist into Postgres under a dynamic column name derived from question
    # Use snake_case to create a stable core name and prefix with 'human_'
    col_core = snake_case(payload.question, max_len=56) if snake_case else None
    col_name = f"human_{col_core}" if col_core else f"human_col" 

    try:
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col_name, classification_json, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")
    
    await update_inclusion_decision(sr, citation_id, payload.screening_step, "human")

    return {"status": "success", "sr_id": sr_id, "citation_id": citation_id, "column": col_name, "classification": classification_json}


@router.post("/title-abstract/run")
async def run_title_abstract_agentic(
    payload: TitleAbstractRunRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Run orchestrated Title/Abstract screening + critical for one citation.

    Implements Phase 1 MVP endpoint from planning/agentic_implementation_plan.
    """

    sr_id = str(payload.sr_id)
    citation_id = int(payload.citation_id)

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    table_name = (screening or {}).get("table_name") or "citations"

    # Ensure LLM client is available
    if not azure_openai_client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure OpenAI client is not configured on the server",
        )

    # Load citation row
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Build combined citation text (use SR include columns or fallback to title+abstract)
    include_cols = []
    try:
        include_cols = cits_dp_service.load_include_columns_from_criteria(sr) or []
    except Exception:
        include_cols = []
    if not include_cols:
        include_cols = ["title", "abstract"]

    citation_text = citations_router._build_combined_citation_from_row(row, include_cols)

    # Load L1 criteria
    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    l1 = cp.get("l1") if isinstance(cp, dict) else None
    questions = (l1 or {}).get("questions") if isinstance(l1, dict) else []
    possible = (l1 or {}).get("possible_answers") if isinstance(l1, dict) else []
    addinfos = (l1 or {}).get("additional_infos") if isinstance(l1, dict) else []
    questions = questions if isinstance(questions, list) else []
    possible = possible if isinstance(possible, list) else []
    addinfos = addinfos if isinstance(addinfos, list) else []

    if not questions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SR has no L1 criteria questions configured")

    async def _call_llm(prompt: str) -> Tuple[str, Dict[str, Any], int]:
        """Return (content, usage, latency_ms)."""
        import time

        t0 = time.time()
        messages = [{"role": "user", "content": prompt}]
        resp = await azure_openai_client.chat_completion(
            messages=messages,
            model=payload.model,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            stream=False,
        )
        latency_ms = int((time.time() - t0) * 1000)
        content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        return str(content), dict(usage), latency_ms

    results: List[Dict[str, Any]] = []
    user_email = str(current_user.get("email") or current_user.get("id") or "")

    for i, q in enumerate(questions):
        if not isinstance(q, str) or not q.strip():
            continue

        opts = possible[i] if i < len(possible) and isinstance(possible[i], list) else []
        opts = [str(o) for o in opts if o is not None and str(o).strip()]
        xtra = addinfos[i] if i < len(addinfos) and isinstance(addinfos[i], str) else ""

        if not opts:
            # still return shape to UI
            results.append(
                {
                    "question": q,
                    "criterion_key": snake_case(q, max_len=56),
                    "error": "No options configured",
                }
            )
            continue

        options_listed = "\n".join(opts)
        criterion_key = snake_case(q, max_len=56)

        # 1) screening
        screening_prompt = PROMPT_XML_TEMPLATE_TA.format(
            question=q,
            cit=citation_text,
            options=options_listed,
            xtra=xtra or "",
        )
        screening_raw, screening_usage, screening_latency = await _call_llm(screening_prompt)
        screening_parsed = parse_agent_xml(screening_raw)
        screening_answer = resolve_option(screening_parsed.answer, opts)

        try:
            screening_run_id = await run_in_threadpool(
                cits_dp_service.insert_screening_agent_run,
                {
                    "sr_id": sr_id,
                    "table_name": table_name,
                    "citation_id": citation_id,
                    "pipeline": "title_abstract",
                    "criterion_key": criterion_key,
                    "stage": "screening",
                    "answer": screening_answer,
                    "confidence": screening_parsed.confidence,
                    "rationale": screening_parsed.rationale,
                    "raw_response": screening_raw,
                    "model": payload.model,
                    "prompt_version": payload.prompt_version,
                    "temperature": payload.temperature,
                    "latency_ms": screening_latency,
                    "input_tokens": screening_usage.get("prompt_tokens"),
                    "output_tokens": screening_usage.get("completion_tokens"),
                },
            )
        except RuntimeError as rexc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to persist screening run: {e}")

        # 2) critical
        critical_opts = build_critical_options(all_options=opts, screening_answer=screening_answer)
        critical_listed = "\n".join(critical_opts)
        critical_prompt = PROMPT_XML_TEMPLATE_TA_CRITICAL.format(
            question=q,
            cit=citation_text,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or "",
        )
        critical_raw, critical_usage, critical_latency = await _call_llm(critical_prompt)
        critical_parsed = parse_agent_xml(critical_raw)
        critical_answer = resolve_option(critical_parsed.answer, critical_opts)

        disagrees = str(critical_answer).strip() != "None of the above"

        try:
            critical_run_id = await run_in_threadpool(
                cits_dp_service.insert_screening_agent_run,
                {
                    "sr_id": sr_id,
                    "table_name": table_name,
                    "citation_id": citation_id,
                    "pipeline": "title_abstract",
                    "criterion_key": criterion_key,
                    "stage": "critical",
                    "answer": critical_answer,
                    "confidence": critical_parsed.confidence,
                    "rationale": critical_parsed.rationale,
                    "raw_response": critical_raw,
                    "model": payload.model,
                    "prompt_version": payload.prompt_version,
                    "temperature": payload.temperature,
                    "latency_ms": critical_latency,
                    "input_tokens": critical_usage.get("prompt_tokens"),
                    "output_tokens": critical_usage.get("completion_tokens"),
                },
            )
        except RuntimeError as rexc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to persist critical run: {e}")

        results.append(
            {
                "question": q,
                "criterion_key": criterion_key,
                "screening": {
                    "run_id": screening_run_id,
                    "answer": screening_answer,
                    "confidence": screening_parsed.confidence,
                    "rationale": screening_parsed.rationale,
                    "parse_ok": screening_parsed.parse_ok,
                },
                "critical": {
                    "run_id": critical_run_id,
                    "answer": critical_answer,
                    "confidence": critical_parsed.confidence,
                    "rationale": critical_parsed.rationale,
                    "parse_ok": critical_parsed.parse_ok,
                    "disagrees": disagrees,
                },
            }
        )

    return {
        "status": "success",
        "sr_id": sr_id,
        "citation_id": citation_id,
        "pipeline": "title_abstract",
        "criteria": results,
    }


@router.post("/validate")
async def validate_screening_step(
    payload: ValidateStepRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Mark a citation as validated for a given step.

    Phase 1 MVP uses step=l1 (Title/Abstract). This endpoint is written to be
    forward-compatible with l2/parameters.
    """

    sr_id = str(payload.sr_id)
    citation_id = int(payload.citation_id)
    step = (payload.step or "l1").lower().strip()
    checked = bool(payload.checked)

    if step not in {"l1", "l2", "parameters"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="step must be one of: l1, l2, parameters")

    try:
        _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load SR: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # New storage: per-step validations list (JSONB)
    validations_col = f"{step}_validations"
    validated_by_col = f"{step}_validated_by"       # legacy summary
    validated_at_col = f"{step}_validated_at"       # legacy summary

    user_email = str(current_user.get("email") or current_user.get("id") or "").strip()
    now_iso = datetime.utcnow().isoformat() + "Z"

    try:
        # Ensure columns exist (best-effort; no-migrations philosophy)
        await run_in_threadpool(cits_dp_service.create_column, validations_col, "JSONB", table_name)
        await run_in_threadpool(cits_dp_service.create_column, validated_by_col, "TEXT", table_name)
        await run_in_threadpool(cits_dp_service.create_column, validated_at_col, "TIMESTAMPTZ", table_name)

        # Load row to get existing validations list
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

        existing = _as_validation_list(row.get(validations_col))

        if checked:
            # Upsert (replace existing entry for this user with new timestamp)
            existing = [x for x in existing if str(x.get("user") or "") != user_email]
            existing.append({"user": user_email, "validated_at": now_iso})
        else:
            # Remove
            existing = [x for x in existing if str(x.get("user") or "") != user_email]

        normalized = _dedupe_validations(existing)

        u_list = await run_in_threadpool(
            cits_dp_service.update_jsonb_column,
            citation_id,
            validations_col,
            normalized,
            table_name,
        )

        # Keep legacy summary fields in sync for existing UI/components:
        # - if list empty => NULL out by/at
        # - else => most recent validation
        if not normalized:
            await run_in_threadpool(cits_dp_service.clear_columns, citation_id, [validated_by_col, validated_at_col], table_name)
            summary_by = None
            summary_at = None
        else:
            summary_by = normalized[0].get("user")
            summary_at = normalized[0].get("validated_at")
            await run_in_threadpool(cits_dp_service.update_text_column, citation_id, validated_by_col, str(summary_by or ""), table_name)
            await run_in_threadpool(cits_dp_service.update_text_column, citation_id, validated_at_col, str(summary_at or ""), table_name)

    except HTTPException:
        raise
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update validation fields: {e}")

    if not u_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    return {
        "status": "success",
        "sr_id": sr_id,
        "citation_id": citation_id,
        "step": step,
        "checked": checked,
        "user": user_email,
        "validated_at": now_iso if checked else None,
        "validations": normalized,
        "summary_validated_by": summary_by,
        "summary_validated_at": summary_at,
    }


@router.post("/fulltext/run")
async def run_fulltext_agentic(
    payload: FulltextRunRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Run orchestrated Fulltext screening + critical for one citation (L2)."""

    sr_id = str(payload.sr_id)
    citation_id = int(payload.citation_id)

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load SR: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    if not azure_openai_client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure OpenAI client is not configured on the server",
        )

    # Load citation row
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Ensure fulltext exists (CAN-SR source of truth: extracted DI/Grobid artifacts)
    if not row.get("fulltext"):
        # We don't have a direct SR id in the extract endpoint signature; it expects sr_id.
        # We'll try best-effort to trigger extraction if fulltext_url exists.
        try:
            from ..extract.router import extract_fulltext_from_storage

            await extract_fulltext_from_storage(sr_id, citation_id, current_user=current_user)  # type: ignore
        except Exception:
            pass

        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)

    include_cols = []
    try:
        include_cols = cits_dp_service.load_include_columns_from_criteria(sr) or []
    except Exception:
        include_cols = []
    if not include_cols:
        include_cols = ["title", "abstract"]

    citation_text = citations_router._build_combined_citation_from_row(row or {}, include_cols)
    fulltext = (row or {}).get("fulltext") or citation_text

    # Tables/Figures context from row
    tables_md_lines: List[str] = []
    figures_lines: List[str] = []
    images: List[Tuple[bytes, str]] = []

    ft_tables = (row or {}).get("fulltext_tables")
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

    ft_figs = (row or {}).get("fulltext_figures")
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

    # Load L2 criteria
    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    l2 = cp.get("l2") if isinstance(cp, dict) else None
    questions = (l2 or {}).get("questions") if isinstance(l2, dict) else []
    possible = (l2 or {}).get("possible_answers") if isinstance(l2, dict) else []
    addinfos = (l2 or {}).get("additional_infos") if isinstance(l2, dict) else []
    questions = questions if isinstance(questions, list) else []
    possible = possible if isinstance(possible, list) else []
    addinfos = addinfos if isinstance(addinfos, list) else []

    if not questions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SR has no L2 criteria questions configured")

    async def _call_llm(prompt: str) -> Tuple[str, Dict[str, Any], int]:
        import time

        t0 = time.time()
        # Use multimodal API when we have figure images
        if images:
            content = await azure_openai_client.multimodal_chat(
                user_text=prompt,
                images=images,
                system_prompt=None,
                model=payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
            )
            latency_ms = int((time.time() - t0) * 1000)
            # multimodal_chat does not expose usage
            return str(content), {}, latency_ms

        messages = [{"role": "user", "content": prompt}]
        resp = await azure_openai_client.chat_completion(
            messages=messages,
            model=payload.model,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            stream=False,
        )
        latency_ms = int((time.time() - t0) * 1000)
        content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        return str(content), dict(usage), latency_ms

    results: List[Dict[str, Any]] = []

    for i, q in enumerate(questions):
        if not isinstance(q, str) or not q.strip():
            continue

        opts = possible[i] if i < len(possible) and isinstance(possible[i], list) else []
        opts = [str(o) for o in opts if o is not None and str(o).strip()]
        xtra = addinfos[i] if i < len(addinfos) and isinstance(addinfos[i], str) else ""

        if not opts:
            results.append({"question": q, "criterion_key": snake_case(q, max_len=56), "error": "No options configured"})
            continue

        criterion_key = snake_case(q, max_len=56)
        options_listed = "\n".join(opts)

        # 1) screening
        screening_prompt = PROMPT_XML_TEMPLATE_FULLTEXT.format(
            question=q,
            options=options_listed,
            xtra=xtra or "",
            fulltext=fulltext,
            tables="\n".join(tables_md_lines) if tables_md_lines else "(none)",
            figures="\n".join(figures_lines) if figures_lines else "(none)",
        )
        screening_raw, screening_usage, screening_latency = await _call_llm(screening_prompt)
        screening_parsed = parse_agent_xml(screening_raw)
        screening_answer = resolve_option(screening_parsed.answer, opts)

        try:
            screening_run_id = await run_in_threadpool(
                cits_dp_service.insert_screening_agent_run,
                {
                    "sr_id": sr_id,
                    "table_name": table_name,
                    "citation_id": citation_id,
                    "pipeline": "fulltext",
                    "criterion_key": criterion_key,
                    "stage": "screening",
                    "answer": screening_answer,
                    "confidence": screening_parsed.confidence,
                    "rationale": screening_parsed.rationale,
                    "raw_response": screening_raw,
                    "model": payload.model,
                    "prompt_version": payload.prompt_version,
                    "temperature": payload.temperature,
                    "latency_ms": screening_latency,
                    "input_tokens": screening_usage.get("prompt_tokens"),
                    "output_tokens": screening_usage.get("completion_tokens"),
                },
            )
        except RuntimeError as rexc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to persist screening run: {e}")

        # 2) critical
        critical_opts = build_critical_options(all_options=opts, screening_answer=screening_answer)
        critical_listed = "\n".join(critical_opts)
        critical_prompt = PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL.format(
            question=q,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or "",
            fulltext=fulltext,
            tables="\n".join(tables_md_lines) if tables_md_lines else "(none)",
            figures="\n".join(figures_lines) if figures_lines else "(none)",
        )
        critical_raw, critical_usage, critical_latency = await _call_llm(critical_prompt)
        critical_parsed = parse_agent_xml(critical_raw)
        critical_answer = resolve_option(critical_parsed.answer, critical_opts)
        disagrees = str(critical_answer).strip() != "None of the above"

        try:
            critical_run_id = await run_in_threadpool(
                cits_dp_service.insert_screening_agent_run,
                {
                    "sr_id": sr_id,
                    "table_name": table_name,
                    "citation_id": citation_id,
                    "pipeline": "fulltext",
                    "criterion_key": criterion_key,
                    "stage": "critical",
                    "answer": critical_answer,
                    "confidence": critical_parsed.confidence,
                    "rationale": critical_parsed.rationale,
                    "raw_response": critical_raw,
                    "model": payload.model,
                    "prompt_version": payload.prompt_version,
                    "temperature": payload.temperature,
                    "latency_ms": critical_latency,
                    "input_tokens": critical_usage.get("prompt_tokens"),
                    "output_tokens": critical_usage.get("completion_tokens"),
                },
            )
        except RuntimeError as rexc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to persist critical run: {e}")

        results.append(
            {
                "question": q,
                "criterion_key": criterion_key,
                "screening": {
                    "run_id": screening_run_id,
                    "answer": screening_answer,
                    "confidence": screening_parsed.confidence,
                    "rationale": screening_parsed.rationale,
                    "parse_ok": screening_parsed.parse_ok,
                },
                "critical": {
                    "run_id": critical_run_id,
                    "answer": critical_answer,
                    "confidence": critical_parsed.confidence,
                    "rationale": critical_parsed.rationale,
                    "parse_ok": critical_parsed.parse_ok,
                    "disagrees": disagrees,
                },
            }
        )

    return {
        "status": "success",
        "sr_id": sr_id,
        "citation_id": citation_id,
        "pipeline": "fulltext",
        "criteria": results,
    }


@router.get("/agent-runs/latest", response_model=AgentRunsQueryResponse)
async def get_latest_agent_runs(
    sr_id: str,
    pipeline: str,
    citation_ids: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Fetch latest screening_agent_runs for a set of citations.

    Query params:
      - sr_id: SR id
      - pipeline: title_abstract | fulltext
      - citation_ids: comma-separated citation ids
    """

    pipeline_norm = (pipeline or "").strip().lower()
    if pipeline_norm in {"ta", "titleabstract", "title-abstract"}:
        pipeline_norm = "title_abstract"
    if pipeline_norm not in {"title_abstract", "fulltext"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pipeline must be 'title_abstract' or 'fulltext'")

    raw_ids = [p.strip() for p in (citation_ids or "").split(",") if p.strip()]
    if not raw_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="citation_ids is required")
    parsed_ids: List[int] = []
    for p in raw_ids:
        try:
            parsed_ids.append(int(p))
        except Exception:
            continue
    if not parsed_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="citation_ids must be a comma-separated list of integers")

    try:
        _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load SR: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    try:
        rows = await run_in_threadpool(
            cits_dp_service.list_latest_agent_runs,
            sr_id=sr_id,
            table_name=table_name,
            citation_ids=parsed_ids,
            pipeline=pipeline_norm,
        )
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening_agent_runs: {e}")

    return AgentRunsQueryResponse(sr_id=sr_id, pipeline=pipeline_norm, citation_ids=parsed_ids, runs=rows)


@router.get("/metrics", response_model=ScreeningMetricsResponse)
async def get_screening_metrics(
    sr_id: str,
    step: str = "l1",
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Return per-criterion metrics + validation summaries for a screening step.

    - Each criterion uses its own threshold (from SR.screening_thresholds[step][criterion_key]).
    - Needs-human-review logic:
        1) If ANY criterion is a confident exclude => no human review needed for the citation.
        2) Else if ANY criterion has critical disagreement => needs review.
        3) Else if ANY criterion is low confidence (below its threshold) => needs review.
    """

    step_norm = str(step or "l1").lower().strip()
    if step_norm not in {"l1", "l2"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="step must be l1 or l2")

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load SR: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Criteria questions for step
    cp = sr.get("criteria_parsed") or {}
    crit_block = cp.get(step_norm) if isinstance(cp, dict) else None
    questions = (crit_block or {}).get("questions") if isinstance(crit_block, dict) else []
    questions = questions if isinstance(questions, list) else []

    # Threshold map
    sr_thresholds = sr.get("screening_thresholds") or {}
    step_thresholds = sr_thresholds.get(step_norm) if isinstance(sr_thresholds, dict) else None
    step_thresholds = step_thresholds if isinstance(step_thresholds, dict) else {}

    # Build criterion list (key + label + threshold)
    criteria: List[Dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, str) or not q.strip():
            continue
        ck = _criterion_key_from_question(q)
        thr_raw = step_thresholds.get(ck)
        try:
            thr = float(thr_raw)
            thr = max(0.0, min(1.0, thr))
        except Exception:
            thr = 0.9
        criteria.append({"criterion_key": ck, "label": q, "threshold": thr})

    # Pull all citation ids for this step (L2 list is filtered by human_l1_decision include)
    filter_step = ""
    if step_norm == "l2":
        filter_step = "l1"
    try:
        ids = await run_in_threadpool(cits_dp_service.list_citation_ids, filter_step, table_name)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list citations: {e}")

    # Load only columns we need
    needed_cols: List[str] = ["id"]
    validations_col = f"{step_norm}_validations"
    legacy_validated_by = f"{step_norm}_validated_by"

    needed_cols.extend([validations_col, legacy_validated_by])

    # We'll compute per-citation needs-review based on agent runs only.
    # Fetch latest runs for all citations (bulk query using service helper)
    pipeline_norm = "title_abstract" if step_norm == "l1" else "fulltext"
    try:
        runs = await run_in_threadpool(
            cits_dp_service.list_latest_agent_runs,
            sr_id=sr_id,
            table_name=table_name,
            citation_ids=ids,
            pipeline=pipeline_norm,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load agent runs: {e}")

    # Group runs by citation then criterion
    runs_by_cit: Dict[int, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    for r in runs or []:
        try:
            cid = int(r.get("citation_id"))
        except Exception:
            continue
        ck = str(r.get("criterion_key") or "")
        stg = str(r.get("stage") or "")
        if not ck or stg not in {"screening", "critical"}:
            continue
        if cid not in runs_by_cit:
            runs_by_cit[cid] = {}
        if ck not in runs_by_cit[cid]:
            runs_by_cit[cid][ck] = {}
        runs_by_cit[cid][ck][stg] = r

    # Load citation rows for validations (and to know total citations count)
    # If ids huge, this could be heavy; acceptable for now, can paginate later.
    try:
        rows = await run_in_threadpool(cits_dp_service.get_citations_by_ids, ids, table_name, needed_cols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load citation rows: {e}")

    # Helper: is validated?
    def _is_validated(row: Dict[str, Any]) -> bool:
        v = row.get(validations_col)
        if v:
            try:
                parsed = v
                if isinstance(v, str):
                    parsed = json.loads(v)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return True
            except Exception:
                pass
        return bool(row.get(legacy_validated_by))

    # Per-criterion aggregates
    agg: Dict[str, Dict[str, int]] = {}
    for c in criteria:
        ck = c["criterion_key"]
        agg[ck] = {
            "total_citations": 0,
            "has_run_count": 0,
            "low_confidence_count": 0,
            "critical_disagreement_count": 0,
            "confident_exclude_count": 0,
            "needs_human_review_count": 0,
        }

    total_citations = 0
    validated_all = 0
    needs_review_total = 0
    validated_needs_review = 0

    # Iterate citations and compute needs-review + per-criterion counts
    for row in rows or []:
        try:
            cid = int(row.get("id"))
        except Exception:
            continue
        total_citations += 1
        validated = _is_validated(row)
        if validated:
            validated_all += 1

        per_crit = runs_by_cit.get(cid, {})

        # Evaluate confident exclude override
        has_confident_exclude = False
        has_critical_disagreement = False
        has_low_confidence = False

        for c in criteria:
            ck = c["criterion_key"]
            thr = float(c["threshold"])
            a = agg.get(ck)
            if a is None:
                continue
            a["total_citations"] += 1

            rpair = per_crit.get(ck) or {}
            scr = rpair.get("screening")
            crit = rpair.get("critical")

            if scr:
                a["has_run_count"] += 1
                conf = scr.get("confidence")
                try:
                    conf_f = float(conf)
                except Exception:
                    conf_f = None
                ans = scr.get("answer")

                if conf_f is not None and conf_f < thr:
                    a["low_confidence_count"] += 1
                    has_low_confidence = True

                if conf_f is not None and conf_f >= thr and _is_exclude_answer(ans):
                    a["confident_exclude_count"] += 1
                    has_confident_exclude = True

            if crit and _is_disagreeing_critical_answer(crit.get("answer")):
                a["critical_disagreement_count"] += 1
                has_critical_disagreement = True

        needs_review = (not has_confident_exclude) and (has_critical_disagreement or has_low_confidence)
        if needs_review:
            needs_review_total += 1
            if validated:
                validated_needs_review += 1
            # increment per-criterion needs-review count for all criteria
            for c in criteria:
                agg[c["criterion_key"]]["needs_human_review_count"] += 1

    unvalidated_all = max(0, total_citations - validated_all)
    unvalidated_needs_review = max(0, needs_review_total - validated_needs_review)

    # Build response
    crit_out: List[Dict[str, Any]] = []
    for c in criteria:
        ck = c["criterion_key"]
        a = agg.get(ck) or {}
        crit_out.append(
            {
                "criterion_key": ck,
                "label": c["label"],
                "threshold": float(c["threshold"]),
                **a,
            }
        )

    return ScreeningMetricsResponse(
        sr_id=sr_id,
        steps={
            step_norm: {
                "summary": {
                    "step": step_norm,
                    "total_citations": total_citations,
                    "validated_all": validated_all,
                    "unvalidated_all": unvalidated_all,
                    "needs_review_total": needs_review_total,
                    "validated_needs_review": validated_needs_review,
                    "unvalidated_needs_review": unvalidated_needs_review,
                },
                "criteria": crit_out,
            }
        },
    )

async def update_inclusion_decision(
    sr: Dict[str, Any],
    citation_id: int,
    screening_step: str,
    decision_maker: str,
):  
    table_name = (sr.get("screening_db") or {}).get("table_name") or "citations"

    # IMPORTANT: decision/pass computation must not be stale.
    # Always re-fetch the citation row when computing decisions, because callers may
    # have just written human/llm columns earlier in the request.
    def _get_row_fresh() -> Dict[str, Any]:
        r = cits_dp_service.get_citation_by_id(int(citation_id), table_name)
        return r or {}

    try:
        row = await run_in_threadpool(_get_row_fresh)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")
    
    questions = sr["criteria_parsed"][screening_step]["questions"]
    classified = True
    decision = "undecided"
    for question in questions:
        col_core = snake_case(question, max_len=56) if snake_case else None
        col_name = f"{decision_maker}_{col_core}"
        result = row.get(col_name)
        if result is None:
            classified = False
            break
        selected = result["selected"]
        if "exclude" in str(selected).lower():
            decision = "exclude"

    if classified and decision == "undecided":
        decision = "include"
    
    col_name = f"{decision_maker}_{screening_step}_decision"
    try:
        updated = await run_in_threadpool(cits_dp_service.update_text_column, citation_id, col_name, decision, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")
    print(updated)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    # Validation rule (B1/B2): do NOT use l1_screen/l2_screen for filtering.
    # Ensure human_l1_decision / human_l2_decision are always correct and derived
    # from the current DB state.
    try:
        fresh = await run_in_threadpool(_get_row_fresh)

        def _compute_human_decision(step: str) -> str:
            """Compute derived human decisions used for filtering.

            Rules:
            - human_l1_decision is derived ONLY from L1 questions.
            - human_l2_decision represents "passed to L2/extract" and must consider
              BOTH L1 + L2 criteria questions.
            """
            cp = sr.get("criteria_parsed") or {}

            # L1: only L1 questions
            if step == "l1":
                qs = (cp.get("l1") or {}).get("questions") or []
            # L2: union of L1 + L2 questions
            elif step == "l2":
                l1_qs = (cp.get("l1") or {}).get("questions") or []
                l2_qs = (cp.get("l2") or {}).get("questions") or []
                qs = list(l1_qs) + list(l2_qs)
            else:
                qs = (cp.get(step) or {}).get("questions") or []

            if not isinstance(qs, list) or not qs:
                return "undecided"

            for q in qs:
                core = snake_case(q, max_len=56) if snake_case else ""
                hcol = f"human_{core}" if core else "human_col"
                hval = fresh.get(hcol)
                if hval is None:
                    return "undecided"
                try:
                    hobj = json.loads(hval) if isinstance(hval, str) else hval
                    selected = (hobj or {}).get("selected")
                except Exception:
                    selected = None
                # Treat empty/whitespace as unanswered (UI shows "-- select --")
                if selected is None or (isinstance(selected, str) and selected.strip() == ""):
                    return "undecided"
                if "exclude" in str(selected).lower():
                    return "exclude"

            return "include"

        # Always set both human decisions on any update, so the list filters never go stale.
        h1 = _compute_human_decision("l1")
        h2 = _compute_human_decision("l2")
        await run_in_threadpool(cits_dp_service.update_text_column, citation_id, "human_l1_decision", h1, table_name)
        await run_in_threadpool(cits_dp_service.update_text_column, citation_id, "human_l2_decision", h2, table_name)
    except Exception:
        # best-effort; do not block response
        pass
