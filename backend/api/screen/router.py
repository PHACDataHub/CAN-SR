from typing import Any, Dict, List, Optional, Tuple
import math
import json
import re
from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
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
    accuracy: Optional[float] = None
    # NOTE: this is NOT human accuracy; it is agreement between screening + critical agents.
    accuracy_critical_agent: Optional[float] = None


class ScreeningMetricsSummary(BaseModel):
    step: str
    total_citations: int
    validated_all: int
    unvalidated_all: int
    validated_needs_review: int
    unvalidated_needs_review: int
    needs_review_total: int
    not_screened_yet: int
    auto_excluded: int


class ScreeningMetricsResponse(BaseModel):
    sr_id: str
    steps: Dict[str, Any]
    warnings: Optional[List[Dict[str, Any]]] = None


class CalibrationPoint(BaseModel):
    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int
    precision: Optional[float] = None
    recall: Optional[float] = None
    fpr: Optional[float] = None
    tpr: Optional[float] = None
    workload_reduction: Optional[float] = None


class CalibrationHistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    agree: int
    disagree: int


class CalibrationCriterionResponse(BaseModel):
    criterion_key: str
    label: str
    validated_n: int
    recommended_threshold: Optional[float] = None
    recommended_reason: Optional[str] = None
    curve: List[CalibrationPoint]
    histogram: List[CalibrationHistogramBin]


class CalibrationResponse(BaseModel):
    sr_id: str
    step: str
    criteria: List[CalibrationCriterionResponse]


class CalibrationSampleRow(BaseModel):
    citation_id: int
    criterion_key: str
    label: str
    validated: bool
    confidence: Optional[float] = None
    ai_answer: Optional[str] = None
    human_selected: Optional[str] = None
    agrees: Optional[bool] = None
    bucket: Optional[str] = None  # tp/fp/fn/tn given a threshold


class CalibrationSamplesResponse(BaseModel):
    sr_id: str
    step: str
    threshold: float
    rows: List[CalibrationSampleRow]


def _csv_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    # RFC 4180 basic escaping
    if any(ch in s for ch in [",", "\n", "\r", '"']):
        s = '"' + s.replace('"', '""') + '"'
    return s


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


def _parse_selected_from_human_payload(v: Any) -> Optional[str]:
    """Extract the human label (selected option) from a human_{criterion_key} cell.

    Stored value is usually JSONB like:
      {"selected": "...", "confidence": ..., ...}
    but some deployments might store a plain string.
    """
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # Try JSON first
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                sel = obj.get("selected")
                return str(sel).strip() if isinstance(sel, str) else None
        except Exception:
            return s
        return None
    if isinstance(v, dict):
        sel = v.get("selected")
        return str(sel).strip() if isinstance(sel, str) else None
    return None


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


def _questions_for_step(cp: Any, step_norm: str) -> List[str]:
    """Return criteria questions for a step.

    IMPORTANT: For L2 we still apply L1 criteria during full-text screening,
    so L2 == (L1 questions + L2 questions).
    """

    if not isinstance(cp, dict):
        return []

    def _get(step_key: str) -> List[str]:
        blk = cp.get(step_key)
        if not isinstance(blk, dict):
            return []
        qs = blk.get("questions")
        if not isinstance(qs, list):
            return []
        out: List[str] = []
        for q in qs:
            if isinstance(q, str) and q.strip():
                out.append(q)
        return out

    if step_norm == "l2":
        seen: set[str] = set()
        merged: List[str] = []
        for q in _get("l1") + _get("l2"):
            if q in seen:
                continue
            seen.add(q)
            merged.append(q)
        return merged

    return _get(step_norm)



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
                    "guardrails": _build_guardrails(screening_parsed, raw_text=screening_raw, stage="screening"),
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
        critical_additions = ""
        try:
            cpa = sr.get("critical_prompt_additions") or {}
            if isinstance(cpa, dict):
                block = cpa.get("l1")
                if isinstance(block, dict):
                    critical_additions = str(block.get(criterion_key) or "")
        except Exception:
            critical_additions = ""
        if not critical_additions.strip():
            critical_additions = "(none)"

        critical_opts = build_critical_options(all_options=opts, screening_answer=screening_answer)
        critical_listed = "\n".join(critical_opts)
        critical_prompt = PROMPT_XML_TEMPLATE_TA_CRITICAL.format(
            question=q,
            cit=citation_text,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or "",
            critical_additions=critical_additions,
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
                    "guardrails": _build_guardrails(critical_parsed, raw_text=critical_raw, stage="critical"),
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

    # Load L2 criteria (L2 = L1 + L2 questions)
    cp = sr.get("criteria_parsed") or sr.get("criteria") or {}
    l1_blk = cp.get("l1") if isinstance(cp, dict) else None
    l2_blk = cp.get("l2") if isinstance(cp, dict) else None

    l1_questions = (l1_blk or {}).get("questions") if isinstance(l1_blk, dict) else []
    l2_questions = (l2_blk or {}).get("questions") if isinstance(l2_blk, dict) else []
    l1_possible = (l1_blk or {}).get("possible_answers") if isinstance(l1_blk, dict) else []
    l2_possible = (l2_blk or {}).get("possible_answers") if isinstance(l2_blk, dict) else []
    l1_addinfos = (l1_blk or {}).get("additional_infos") if isinstance(l1_blk, dict) else []
    l2_addinfos = (l2_blk or {}).get("additional_infos") if isinstance(l2_blk, dict) else []

    # Normalize lists
    l1_questions = l1_questions if isinstance(l1_questions, list) else []
    l2_questions = l2_questions if isinstance(l2_questions, list) else []
    l1_possible = l1_possible if isinstance(l1_possible, list) else []
    l2_possible = l2_possible if isinstance(l2_possible, list) else []
    l1_addinfos = l1_addinfos if isinstance(l1_addinfos, list) else []
    l2_addinfos = l2_addinfos if isinstance(l2_addinfos, list) else []

    # Merge preserving order and remembering which block it came from so we can
    # pick the right options/additional_infos.
    merged_questions: List[Tuple[str, str, int]] = []  # (question, source_step, index)
    seen_q: set[str] = set()
    for idx, q in enumerate(l1_questions):
        if not isinstance(q, str) or not q.strip() or q in seen_q:
            continue
        seen_q.add(q)
        merged_questions.append((q, "l1", idx))
    for idx, q in enumerate(l2_questions):
        if not isinstance(q, str) or not q.strip() or q in seen_q:
            continue
        seen_q.add(q)
        merged_questions.append((q, "l2", idx))

    if not merged_questions:
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

    for q, source_step, idx in merged_questions:
        if not isinstance(q, str) or not q.strip():
            continue

        if source_step == "l1":
            opts_raw = l1_possible[idx] if idx < len(l1_possible) and isinstance(l1_possible[idx], list) else []
            xtra = l1_addinfos[idx] if idx < len(l1_addinfos) and isinstance(l1_addinfos[idx], str) else ""
        else:
            opts_raw = l2_possible[idx] if idx < len(l2_possible) and isinstance(l2_possible[idx], list) else []
            xtra = l2_addinfos[idx] if idx < len(l2_addinfos) and isinstance(l2_addinfos[idx], str) else ""

        opts = [str(o) for o in opts_raw if o is not None and str(o).strip()]

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
                    "guardrails": _build_guardrails(screening_parsed, raw_text=screening_raw, stage="screening"),
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
        critical_additions = ""
        try:
            cpa = sr.get("critical_prompt_additions") or {}
            if isinstance(cpa, dict):
                # Prefer L2 additions (fulltext step). If this question originated from L1,
                # fall back to L1 additions when L2 is missing.
                block_l2 = cpa.get("l2") if isinstance(cpa.get("l2"), dict) else {}
                block_l1 = cpa.get("l1") if isinstance(cpa.get("l1"), dict) else {}
                critical_additions = str((block_l2 or {}).get(criterion_key) or "")
                if (not critical_additions.strip()) and source_step == "l1":
                    critical_additions = str((block_l1 or {}).get(criterion_key) or "")
        except Exception:
            critical_additions = ""
        if not critical_additions.strip():
            critical_additions = "(none)"

        critical_opts = build_critical_options(all_options=opts, screening_answer=screening_answer)
        critical_listed = "\n".join(critical_opts)
        critical_prompt = PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL.format(
            question=q,
            screening_answer=screening_answer,
            options=critical_listed,
            xtra=xtra or "",
            critical_additions=critical_additions,
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
                    "guardrails": _build_guardrails(critical_parsed, raw_text=critical_raw, stage="critical"),
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


@router.get("/metrics", response_model=ScreeningMetricsResponse, response_model_exclude_none=True)
async def get_screening_metrics(
    sr_id: str,
    step: str = "l1",
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Return per-criterion metrics + validation summaries for a screening step.

    - Each criterion uses its own threshold (from SR.screening_thresholds[step][criterion_key]).
    - Needs-human-review logic:
        0) Not screened yet: if no agent runs exist for this step/pipeline.
        1) Auto-excluded if ANY criterion is a confident exclude AND critical agrees:
           screening answer contains '(exclude)' AND screening_conf >= threshold AND critical answer == 'None of the above'.
        2) Else needs review if ANY criterion has critical disagreement (critical answer != 'None of the above').
        3) Else needs review if ANY criterion is low confidence (below its threshold).
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

    # Criteria questions for step (L2 includes L1 + L2)
    cp = sr.get("criteria_parsed") or {}
    questions = _questions_for_step(cp, step_norm)

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

    # Phase 2: canonical human labels (per criterion) live in human_{criterion_key} JSONB.
    # We only need these to compute validated-set agreement metrics.
    human_cols: Dict[str, str] = {}
    for c in criteria:
        ck = c["criterion_key"]
        col = f"human_{ck}" if ck else "human_col"
        human_cols[ck] = col
        needed_cols.append(col)

    warnings: List[Dict[str, Any]] = []
    # Legacy safety: do NOT attempt to fabricate agent runs.
    # If legacy llm_* outputs exist but normalized runs are missing, we warn the UI
    # so the user can run run-all (which will force overwrite and create real runs).
    try:
        legacy_needs = await run_in_threadpool(
            cits_dp_service.legacy_needs_rerun,
            sr_id=sr_id,
            table_name=table_name,
            criteria_parsed=cp,
            step=step_norm,
        )
        if legacy_needs:
            warnings.append(
                {
                    "code": "LEGACY_DATA_NEEDS_RUN_ALL",
                    "severity": "warning",
                    "message": "Legacy screening results detected (llm_* columns) but agentic runs are missing. Please run Run-all to regenerate results.",
                    "sr_id": sr_id,
                    "step": step_norm,
                }
            )
    except Exception:
        pass

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
            # Count of citations where THIS criterion triggered needs-review.
            "needs_human_review_count": 0,
            # Validated-set agreement counts (AI screening vs canonical human label).
            "human_agree_count": 0,
            "human_total_count": 0,

            # Fallback proxy when human labels are not available:
            # count how often critical agrees with screening.
            "crit_agree_count": 0,
            "crit_total_count": 0,
        }

    total_citations = 0
    validated_all = 0
    needs_review_total = 0
    validated_needs_review = 0
    not_screened_yet = 0
    auto_excluded = 0

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

        # Bucket 1: Not screened yet (no runs at all)
        if not per_crit:
            not_screened_yet += 1
            continue

        # Evaluate confident exclude override
        has_confident_exclude = False
        has_critical_disagreement = False
        has_low_confidence = False
        has_guardrail_issue = False

        for c in criteria:
            ck = c["criterion_key"]
            thr = float(c["threshold"])
            a = agg.get(ck)
            if a is None:
                continue
            a["total_citations"] += 1

            triggered_this_criterion = False

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

                # If citation is validated and a canonical human label exists, compute agreement.
                if validated:
                    hcol = human_cols.get(ck) or f"human_{ck}"
                    human_sel = _parse_selected_from_human_payload(row.get(hcol))
                    if human_sel is not None:
                        a["human_total_count"] += 1
                        # Agreement definition: exact string match after stripping.
                        if str(human_sel).strip() == str(ans or "").strip():
                            a["human_agree_count"] += 1

                if conf_f is not None and conf_f < thr:
                    a["low_confidence_count"] += 1
                    has_low_confidence = True
                    # This criterion triggers review for this citation.
                    triggered_this_criterion = True

                # Guardrails: missing/failed parse should be treated as needs review.
                try:
                    g = scr.get("guardrails")
                    if isinstance(g, str):
                        g = json.loads(g)
                    if isinstance(g, dict):
                        if g.get("parse_ok") is False or g.get("missing_answer") or g.get("missing_confidence"):
                            has_guardrail_issue = True
                            triggered_this_criterion = True
                except Exception:
                    # If guardrails column exists but is unparsable, treat as issue.
                    if scr.get("guardrails") is not None:
                        has_guardrail_issue = True
                        triggered_this_criterion = True

                # Confident exclude requires critical agreement
                crit_has = bool(crit) and str(crit.get("answer") or "").strip() != ""
                crit_agrees = crit_has and (not _is_disagreeing_critical_answer(crit.get("answer")))
                if crit_has:
                    a["crit_total_count"] += 1
                    if crit_agrees:
                        a["crit_agree_count"] += 1
                if conf_f is not None and conf_f >= thr and _is_exclude_answer(ans) and crit_agrees:
                    a["confident_exclude_count"] += 1
                    has_confident_exclude = True

            # Treat missing/empty critical as disagreement/parse issue (conservative).
            if not crit or str(crit.get("answer") or "").strip() == "":
                a["critical_disagreement_count"] += 1
                has_critical_disagreement = True
                triggered_this_criterion = True
            elif _is_disagreeing_critical_answer(crit.get("answer")):
                a["critical_disagreement_count"] += 1
                has_critical_disagreement = True
                triggered_this_criterion = True

            # Guardrails on critical stage
            try:
                if crit:
                    g2 = crit.get("guardrails")
                    if isinstance(g2, str):
                        g2 = json.loads(g2)
                    if isinstance(g2, dict):
                        if g2.get("parse_ok") is False or g2.get("missing_answer") or g2.get("missing_confidence"):
                            has_guardrail_issue = True
                            triggered_this_criterion = True
            except Exception:
                if crit and crit.get("guardrails") is not None:
                    has_guardrail_issue = True
                    triggered_this_criterion = True

            if triggered_this_criterion:
                a["needs_human_review_count"] += 1

        if has_confident_exclude:
            auto_excluded += 1
        needs_review = (not has_confident_exclude) and (has_critical_disagreement or has_low_confidence or has_guardrail_issue)
        if needs_review:
            needs_review_total += 1
            if validated:
                validated_needs_review += 1

    unvalidated_all = max(0, total_citations - validated_all)
    unvalidated_needs_review = max(0, needs_review_total - validated_needs_review)

    # Build response
    crit_out: List[Dict[str, Any]] = []
    for c in criteria:
        ck = c["criterion_key"]
        a = agg.get(ck) or {}
        # Accuracy is human-vs-AI agreement on the validated set (when canonical human labels exist).
        # Do NOT fall back to critical agreement here (misleading).
        accuracy: Optional[float] = None
        accuracy_critical_agent: Optional[float] = None
        try:
            h_total = int(a.get("human_total_count") or 0)
            h_agree = int(a.get("human_agree_count") or 0)
            if h_total > 0:
                accuracy = (h_agree / h_total)
        except Exception:
            accuracy = None

        # Separate metric: agreement between screening agent and critical agent.
        try:
            crit_total = int(a.get("crit_total_count") or 0)
            crit_agree = int(a.get("crit_agree_count") or 0)
            accuracy_critical_agent = (crit_agree / crit_total) if crit_total > 0 else None
        except Exception:
            accuracy_critical_agent = None

        row: Dict[str, Any] = {
            "criterion_key": ck,
            "label": c["label"],
            "threshold": float(c["threshold"]),
            **a,
        }
        if accuracy is not None:
            row["accuracy"] = accuracy
        if accuracy_critical_agent is not None:
            row["accuracy_critical_agent"] = accuracy_critical_agent
        crit_out.append(row)

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
                    "not_screened_yet": not_screened_yet,
                    "auto_excluded": auto_excluded,
                },
                "criteria": crit_out,
            }
        },
        warnings=warnings or None,
    )


def _safe_div(n: float, d: float) -> Optional[float]:
    try:
        if d == 0:
            return None
        return n / d
    except Exception:
        return None


def _clip01(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return float(default)
        return max(0.0, min(1.0, x))
    except Exception:
        return float(default)


def _parse_confidence(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return max(0.0, min(1.0, x))
    except Exception:
        return None


def _build_guardrails(parsed: Any, *, raw_text: str, stage: str) -> Dict[str, Any]:
    """Build a compact guardrails payload for persisting with screening_agent_runs."""
    raw = str(raw_text or "")
    out: Dict[str, Any] = {
        "schema_version": "v1",
        "stage": str(stage or ""),
        "parse_ok": bool(getattr(parsed, "parse_ok", False)),
        "missing_answer": bool(getattr(parsed, "missing_answer", False)),
        "missing_confidence": bool(getattr(parsed, "missing_confidence", False)),
        "missing_rationale": not bool(str(getattr(parsed, "rationale", "") or "").strip()),
        "raw_len": len(raw),
        "has_answer_tag": "<answer" in raw.lower(),
        "has_confidence_tag": "<confidence" in raw.lower(),
        "has_rationale_tag": "<rationale" in raw.lower(),
    }
    # Flag when confidence appears outside [0,1] in raw (heuristic)
    try:
        conf = float(getattr(parsed, "confidence", 0.0))
        out["confidence_clipped"] = bool(conf in (0.0, 1.0)) and ("confidence" in raw.lower())
    except Exception:
        out["confidence_clipped"] = False
    return out


@router.get("/calibration", response_model=CalibrationResponse)
async def get_screening_calibration(
    sr_id: str,
    step: str = "l1",
    thresholds: str = "0.5,0.6,0.7,0.8,0.85,0.9,0.95",
    bins: int = 10,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Compute calibration curves on the validated set.

    Contract (Phase 2A):
    - Uses validated citations for the step (`${step}_validations` or legacy `${step}_validated_by`).
    - For each criterion:
        - AI label: latest screening run's answer + confidence
        - Human label: `human_{criterion_key}.selected`
    - A "positive" is defined as **AI==Human** (agreement). Disagreement is negative.

    Output:
    - curve: confusion matrix + rates for each threshold (treat agreement as positive)
    - histogram: confidence distribution split by agree/disagree
    - recommended_threshold: best threshold by default objective (maximize Youden's J = TPR - FPR)
      with a recall-first tie-break (higher recall).
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

    # Criteria questions for step (L2 includes L1 + L2)
    cp = sr.get("criteria_parsed") or {}
    questions = _questions_for_step(cp, step_norm)

    criteria: List[Dict[str, str]] = []
    for q in questions:
        if not isinstance(q, str) or not q.strip():
            continue
        ck = _criterion_key_from_question(q)
        criteria.append({"criterion_key": ck, "label": q})

    # Determine SR scope ids for step (same as metrics)
    filter_step = ""
    if step_norm == "l2":
        filter_step = "l1"
    try:
        ids = await run_in_threadpool(cits_dp_service.list_citation_ids, filter_step, table_name)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list citations: {e}")

    # Parse thresholds list
    thr_list: List[float] = []
    for part in str(thresholds or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            thr_list.append(_clip01(float(part), default=0.0))
        except Exception:
            continue
    if not thr_list:
        thr_list = [0.9]
    thr_list = sorted(set([_clip01(t) for t in thr_list]))

    try:
        bins_n = int(bins)
    except Exception:
        bins_n = 10
    bins_n = max(3, min(50, bins_n))

    validations_col = f"{step_norm}_validations"
    legacy_validated_by = f"{step_norm}_validated_by"

    # Build columns for row fetch
    needed_cols: List[str] = ["id", validations_col, legacy_validated_by]
    human_cols: Dict[str, str] = {}
    for c in criteria:
        ck = c["criterion_key"]
        hcol = f"human_{ck}" if ck else "human_col"
        human_cols[ck] = hcol
        needed_cols.append(hcol)

    # Load latest screening runs for all ids in this step/pipeline
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

    # Group screening runs by citation then criterion
    screening_by_cit: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in runs or []:
        try:
            cid = int(r.get("citation_id"))
        except Exception:
            continue
        if str(r.get("stage") or "") != "screening":
            continue
        ck = str(r.get("criterion_key") or "")
        if not ck:
            continue
        if cid not in screening_by_cit:
            screening_by_cit[cid] = {}
        screening_by_cit[cid][ck] = r

    # Load citation rows
    try:
        rows = await run_in_threadpool(cits_dp_service.get_citations_by_ids, ids, table_name, needed_cols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load citation rows: {e}")

    def _is_validated_row(row: Dict[str, Any]) -> bool:
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

    # Build validated examples per criterion: (confidence, agree_bool)
    examples: Dict[str, List[Tuple[float, bool]]] = {c["criterion_key"]: [] for c in criteria}
    for row in rows or []:
        try:
            cid = int(row.get("id"))
        except Exception:
            continue
        if not _is_validated_row(row):
            continue
        scr_map = screening_by_cit.get(cid) or {}
        for c in criteria:
            ck = c["criterion_key"]
            scr = scr_map.get(ck)
            if not scr:
                continue
            conf = _parse_confidence(scr.get("confidence"))
            if conf is None:
                continue
            ai_ans = str(scr.get("answer") or "").strip()
            human_sel = _parse_selected_from_human_payload(row.get(human_cols.get(ck) or f"human_{ck}"))
            if human_sel is None:
                continue
            agree = str(human_sel).strip() == ai_ans
            examples[ck].append((conf, agree))

    # Compute curve + histogram per criterion
    out_criteria: List[CalibrationCriterionResponse] = []
    for c in criteria:
        ck = c["criterion_key"]
        label = c["label"]
        ex = examples.get(ck) or []
        validated_n = len(ex)

        # Histogram bins
        hist: List[CalibrationHistogramBin] = []
        if validated_n > 0:
            for b in range(bins_n):
                start = b / bins_n
                end = (b + 1) / bins_n
                agree_ct = 0
                disagree_ct = 0
                for conf, agree in ex:
                    # include 1.0 in last bin
                    in_bin = (conf >= start and conf < end) or (b == bins_n - 1 and conf == 1.0)
                    if not in_bin:
                        continue
                    if agree:
                        agree_ct += 1
                    else:
                        disagree_ct += 1
                hist.append(
                    CalibrationHistogramBin(
                        bin_start=round(start, 6),
                        bin_end=round(end, 6),
                        agree=agree_ct,
                        disagree=disagree_ct,
                    )
                )
        else:
            for b in range(bins_n):
                start = b / bins_n
                end = (b + 1) / bins_n
                hist.append(CalibrationHistogramBin(bin_start=round(start, 6), bin_end=round(end, 6), agree=0, disagree=0))

        curve: List[CalibrationPoint] = []
        best_thr: Optional[float] = None
        best_score: Optional[float] = None
        best_recall: Optional[float] = None

        for thr in thr_list:
            tp = fp = fn = tn = 0
            # Review queue size for this criterion at this threshold = count(conf < thr) among validated examples.
            # Workload reduction proxy: 1 - queue/total.
            queue = 0

            for conf, agree in ex:
                pred_pos = conf >= thr
                if conf < thr:
                    queue += 1

                if pred_pos and agree:
                    tp += 1
                elif pred_pos and not agree:
                    fp += 1
                elif (not pred_pos) and agree:
                    fn += 1
                else:
                    tn += 1

            precision = _safe_div(tp, tp + fp)
            recall = _safe_div(tp, tp + fn)
            fpr = _safe_div(fp, fp + tn)
            tpr = recall
            workload_reduction = None
            if validated_n > 0:
                workload_reduction = 1.0 - (queue / validated_n)

            curve.append(
                CalibrationPoint(
                    threshold=float(thr),
                    tp=tp,
                    fp=fp,
                    fn=fn,
                    tn=tn,
                    precision=precision,
                    recall=recall,
                    fpr=fpr,
                    tpr=tpr,
                    workload_reduction=workload_reduction,
                )
            )

            # Choose recommended threshold by maximizing Youden's J; tie-break by higher recall.
            if recall is None or fpr is None:
                continue
            score = recall - fpr
            if best_score is None or score > best_score + 1e-9:
                best_score = score
                best_thr = thr
                best_recall = recall
            elif best_score is not None and abs(score - best_score) <= 1e-9:
                # tie-break: higher recall
                if best_recall is None or recall > best_recall + 1e-9:
                    best_thr = thr
                    best_recall = recall

        reason = None
        if best_thr is not None:
            reason = "max_youden_j (tpr-fpr), tie-break: max recall"

        out_criteria.append(
            CalibrationCriterionResponse(
                criterion_key=ck,
                label=label,
                validated_n=validated_n,
                recommended_threshold=float(best_thr) if best_thr is not None else None,
                recommended_reason=reason,
                curve=curve,
                histogram=hist,
            )
        )

    return CalibrationResponse(sr_id=sr_id, step=step_norm, criteria=out_criteria)


@router.get("/calibration/samples")
async def get_calibration_samples(
    sr_id: str,
    step: str = "l1",
    threshold: float = 0.9,
    criterion_key: Optional[str] = None,
    limit: int = 200,
    format: str = "json",
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Return calibration sample rows (validated citations only) for auditing.

    This endpoint is meant for exporting / debugging calibration behavior.

    Definitions:
    - human label: `human_{criterion_key}.selected`
    - AI label: latest `stage=screening` answer for this pipeline
    - agrees: AI answer == human selected
    - bucket at given threshold (positive == agreement, predicted positive == confidence >= threshold):
        tp: pred_pos and agrees
        fp: pred_pos and not agrees
        fn: not pred_pos and agrees
        tn: not pred_pos and not agrees

    Query params:
    - sr_id: SR id
    - step: l1|l2
    - threshold: float [0,1]
    - criterion_key: optional filter for a single criterion
    - limit: max rows returned (default 200, max 2000)
    - format: json|csv
    """

    step_norm = str(step or "l1").lower().strip()
    if step_norm not in {"l1", "l2"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="step must be l1 or l2")

    thr = _clip01(threshold, default=0.9)
    lim = max(1, min(2000, int(limit or 200)))
    fmt = str(format or "json").lower().strip()
    if fmt not in {"json", "csv"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be json or csv")

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load SR: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Criteria questions for step (L2 includes L1 + L2)
    cp = sr.get("criteria_parsed") or {}
    questions = _questions_for_step(cp, step_norm)

    criteria: List[Dict[str, str]] = []
    for q in questions:
        if not isinstance(q, str) or not q.strip():
            continue
        ck = _criterion_key_from_question(q)
        if criterion_key and str(criterion_key).strip() != ck:
            continue
        criteria.append({"criterion_key": ck, "label": q})

    if criterion_key and not criteria:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown criterion_key for this step")

    # Determine SR scope ids for step
    filter_step = ""
    if step_norm == "l2":
        filter_step = "l1"
    try:
        ids = await run_in_threadpool(cits_dp_service.list_citation_ids, filter_step, table_name)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list citations: {e}")

    validations_col = f"{step_norm}_validations"
    legacy_validated_by = f"{step_norm}_validated_by"

    # Build columns for row fetch
    needed_cols: List[str] = ["id", validations_col, legacy_validated_by]
    human_cols: Dict[str, str] = {}
    for c in criteria:
        ck = c["criterion_key"]
        hcol = f"human_{ck}" if ck else "human_col"
        human_cols[ck] = hcol
        needed_cols.append(hcol)

    # Load latest screening runs for all ids
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

    # Group screening runs by citation then criterion
    screening_by_cit: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in runs or []:
        try:
            cid = int(r.get("citation_id"))
        except Exception:
            continue
        if str(r.get("stage") or "") != "screening":
            continue
        ck = str(r.get("criterion_key") or "")
        if not ck:
            continue
        if criterion_key and ck != str(criterion_key).strip():
            continue
        if cid not in screening_by_cit:
            screening_by_cit[cid] = {}
        screening_by_cit[cid][ck] = r

    # Load citation rows
    try:
        rows = await run_in_threadpool(cits_dp_service.get_citations_by_ids, ids, table_name, needed_cols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load citation rows: {e}")

    def _is_validated_row(row: Dict[str, Any]) -> bool:
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

    out_rows: List[CalibrationSampleRow] = []
    for row in rows or []:
        if len(out_rows) >= lim:
            break
        try:
            cid = int(row.get("id"))
        except Exception:
            continue
        if not _is_validated_row(row):
            continue
        scr_map = screening_by_cit.get(cid) or {}
        for c in criteria:
            if len(out_rows) >= lim:
                break
            ck = c["criterion_key"]
            scr = scr_map.get(ck)
            if not scr:
                continue
            conf = _parse_confidence(scr.get("confidence"))
            ai_ans = str(scr.get("answer") or "").strip() if scr.get("answer") is not None else None
            human_sel = _parse_selected_from_human_payload(row.get(human_cols.get(ck) or f"human_{ck}"))
            if human_sel is None:
                continue
            agrees = (str(human_sel).strip() == str(ai_ans or "").strip())
            pred_pos = (conf is not None) and (conf >= thr)
            if pred_pos and agrees:
                bucket = "tp"
            elif pred_pos and (not agrees):
                bucket = "fp"
            elif (not pred_pos) and agrees:
                bucket = "fn"
            else:
                bucket = "tn"

            out_rows.append(
                CalibrationSampleRow(
                    citation_id=cid,
                    criterion_key=ck,
                    label=c["label"],
                    validated=True,
                    confidence=conf,
                    ai_answer=ai_ans,
                    human_selected=human_sel,
                    agrees=agrees,
                    bucket=bucket,
                )
            )

    if fmt == "json":
        return CalibrationSamplesResponse(sr_id=sr_id, step=step_norm, threshold=thr, rows=out_rows)

    # CSV format
    header = [
        "citation_id",
        "criterion_key",
        "label",
        "confidence",
        "ai_answer",
        "human_selected",
        "agrees",
        "bucket",
    ]
    lines = [",".join(header)]
    for r in out_rows:
        lines.append(
            ",".join(
                [
                    _csv_escape(r.citation_id),
                    _csv_escape(r.criterion_key),
                    _csv_escape(r.label),
                    _csv_escape(r.confidence),
                    _csv_escape(r.ai_answer),
                    _csv_escape(r.human_selected),
                    _csv_escape(r.agrees),
                    _csv_escape(r.bucket),
                ]
            )
        )
    csv_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    return Response(content=csv_bytes, media_type="text/csv")

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
