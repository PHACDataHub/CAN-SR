from typing import Any, Dict, List, Optional
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

# Import helpers from citations router to fetch citation rows and build combined citations
from ..citations import router as citations_router
from ..core.cit_utils import load_sr_and_check

# Import consolidated Postgres helpers if available (optional)
from ..services.cit_db_service import cits_dp_service, snake_case_column, snake_case
from .prompts import PROMPT_JSON_TEMPLATE, PROMPT_JSON_TEMPLATE_FULLTEXT

logger = logging.getLogger(__name__)

router = APIRouter()


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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Load citation row (needed for l2 fulltext and for building citation_text)
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Build or use provided citation text (fall back to combined title/abstract when not provided)
    citation_text = payload.citation_text or citations_router._build_combined_citation_from_row(row, payload.include_columns)

    # Prepare prompt (use full-text template for l2, otherwise TA/L1 template)
    options_listed = "\n".join([f"{i}. {opt}" for i, opt in enumerate(payload.options)])
    if (payload.screening_step or "").lower() == "l2":
        fulltext = row.get("fulltext") or ""
        prompt = PROMPT_JSON_TEMPLATE_FULLTEXT.format(
            question=payload.question,
            options=options_listed,
            xtra=payload.xtra or "",
            fulltext=fulltext or citation_text,
        )
    else:
        prompt = PROMPT_JSON_TEMPLATE.format(
            question=payload.question,
            cit=citation_text,
            options=options_listed,
            xtra=payload.xtra or ""
        )

    # Ensure LLM client is available
    if not azure_openai_client.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Azure OpenAI client is not configured on the server")

    # Call the LLM (simple non-streaming chat)
    try:
        llm_response = await azure_openai_client.simple_chat(
            user_message=prompt,
            system_prompt=None,
            model=payload.model,
            max_tokens=payload.max_tokens or 2000,
            temperature=payload.temperature or 0.0,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"LLM call failed: {e}")

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

    # Normalize evidence sentences from model (optional)
    evidence_raw = parsed.get("evidence_sentences", [])
    evidence: List[int] = []
    if isinstance(evidence_raw, list):
        for i in evidence_raw:
            try:
                idx = int(i)
                evidence.append(idx)
            except Exception:
                continue

    classification_json = {
        "selected": resolved_selected,
        "explanation": explanation,
        "confidence": confidence,
        "evidence_sentences": evidence,
        "llm_raw": llm_response,  # raw response for audit
    }

    # Persist into Postgres under a dynamic column name derived from question
    col_name = snake_case_column(payload.question)

    try:
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, db_conn, citation_id, col_name, classification_json, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")
    
    await update_inclusion_decision(sr, citation_id, payload.screening_step, "llm", db_conn)

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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Ensure citation exists and optionally build combined citation text
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id), table_name)
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
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, db_conn, citation_id, col_name, classification_json, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")
    
    await update_inclusion_decision(sr, citation_id, payload.screening_step, "human", db_conn)

    return {"status": "success", "sr_id": sr_id, "citation_id": citation_id, "column": col_name, "classification": classification_json}

async def update_inclusion_decision(
    sr: Dict[str, Any],
    citation_id: int,
    screening_step: str,
    decision_maker: str,
    db_conn: str,

):  
    table_name = (sr.get("screening_db") or {}).get("table_name") or "citations"

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id), table_name)
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
        if "exclude" in selected:
            decision = "exclude"

    if classified and decision == "undecided":
        decision = "include"
    
    col_name = f"{decision_maker}_{screening_step}_decision"
    try:
        updated = await run_in_threadpool(cits_dp_service.update_text_column, db_conn, citation_id, col_name, decision, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")
    print(updated)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")
