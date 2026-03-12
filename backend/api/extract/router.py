from typing import Any, Dict, List, Optional, Tuple
import json
import re
import os
from tempfile import NamedTemporaryFile
import hashlib
from datetime import datetime
from pathlib import Path
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..services.sr_db_service import srdb_service
from ..core.config import settings
from ..core.security import get_current_active_user
from ..services.azure_openai_client import azure_openai_client

# reuse citations helpers to access screening Postgres rows
from ..citations import router as citations_router

from .prompts import PARAMETER_PROMPT_JSON

# storage and grobid services
from ..services.storage import storage_service
from ..services.grobid_service import grobid_service
from ..core.cit_utils import load_sr_and_check

from ..services.azure_docint_client import azure_docint_client
from ..core.docint_coords import normalize_bounding_regions_to_boxes

# Import consolidated Postgres helpers if available (optional)
from ..services.cit_db_service import cits_dp_service, snake_case_param



router = APIRouter()


class ParameterExtractRequest(BaseModel):
    fulltext: Optional[str] = Field(
        None,
        description="Full text with numbered sentences (e.g. '[0] First sentence\\n[1] Second sentence'). If omitted the endpoint will try to read fulltext_url from the screening DB row."
    )
    parameter_name: str = Field(..., description="Short name for the parameter (used as column name slug)")
    parameter_description: str = Field(..., description="Human-friendly description of what to extract")
    model: Optional[str] = Field(None, description="Model to use")
    temperature: Optional[float] = Field(0.0, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(512, ge=1, le=4000)

    # Optional artifacts context (if omitted, server will read from citation row when available)
    tables: Optional[str] = Field(None, description="Optional numbered tables text (markdown).")
    figures: Optional[str] = Field(None, description="Optional numbered figure captions text.")
    attach_figures: Optional[bool] = Field(True, description="If true, attach figure images to the LLM request when available")




class HumanParameterRequest(BaseModel):
    fulltext: Optional[str] = Field(
        None,
        description="Optional numbered full text. If omitted the server will try to read fulltext_url from the screening DB row."
    )
    parameter_name: str = Field(..., description="Short name for the parameter (used as column name slug)")
    found: bool = Field(..., description="Whether the parameter was found (boolean)")
    value: Optional[str] = Field(None, description="Human-provided value (string) or null")
    explanation: Optional[str] = Field("", description="Optional explanation from the human reviewer")
    evidence_sentences: Optional[List[int]] = Field(None, description="Optional list of evidence sentence indices")
    reviewer: Optional[str] = Field(None, description="Optional reviewer id or name")


def _list_set(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


@router.post("/{sr_id}/citations/{citation_id}/extract-parameter")
async def extract_parameter_endpoint(
    sr_id: str,
    citation_id: int,
    payload: ParameterExtractRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Extract a parameter value from full text using an LLM and persist the parsed JSON
    result into the screening Postgres citations table under a dynamic JSONB column
    derived from the parameter name (prefixed with 'llm_param_').
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Obtain fulltext: prefer payload, otherwise read from DB row
    fulltext = payload.fulltext
    row = None
    if not fulltext:
        try:
            row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
        except RuntimeError as rexc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

        fulltext = row.get("fulltext") if "fulltext" in row else None
        if not fulltext:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full text not provided and not available for this citation")

    # Build tables/figures context: prefer payload fields, else fetch from DB row (if loaded)
    tables_text = payload.tables
    figures_text = payload.figures
    images: List[Tuple[bytes, str]] = []

    if (tables_text is None or figures_text is None) and row is None:
        try:
            row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
        except Exception:
            row = None

    if row and (tables_text is None or figures_text is None):
        # tables: embed markdown
        if tables_text is None:
            tables_md_lines: List[str] = []
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
            tables_text = "\n".join(tables_md_lines) if tables_md_lines else "(none)"

        # figures: captions + optionally images
        if figures_text is None:
            figures_lines: List[str] = []
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
                    if payload.attach_figures:
                        try:
                            img_bytes, _ = await storage_service.get_bytes_by_path(blob_addr)
                            if img_bytes:
                                images.append((img_bytes, "image/png"))
                        except Exception:
                            continue
            figures_text = "\n".join(figures_lines) if figures_lines else "(none)"

    tables_text = tables_text if tables_text is not None else "(none)"
    figures_text = figures_text if figures_text is not None else "(none)"

    # Build prompt
    prompt = PARAMETER_PROMPT_JSON.format(
        parameter_name=payload.parameter_name,
        parameter_description=payload.parameter_description,
        fulltext=fulltext,
        tables=tables_text,
        figures=figures_text,
    )

    if not azure_openai_client.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Azure OpenAI client is not configured on the server")

    try:
        if images:
            llm_response = await azure_openai_client.multimodal_chat(
                user_text=prompt,
                images=images,
                system_prompt=None,
                model=payload.model,
                max_tokens=payload.max_tokens or 512,
                temperature=payload.temperature or 0.0,
            )
        else:
            llm_response = await azure_openai_client.simple_chat(
                user_message=prompt,
                system_prompt=None,
                model=payload.model,
                max_tokens=payload.max_tokens or 512,
                temperature=payload.temperature or 0.0,
            )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"LLM call failed: {e}")

    # Parse JSON with robustness: tolerate code fences or preamble text
    def _extract_json_object(text: str) -> Optional[str]:
        t = text.strip()
        # strip leading/trailing code fences
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        # find first balanced {...}
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
                    return t[start:i+1]
        return None

    parsed = None
    try:
        parsed = json.loads(llm_response)
    except Exception:
        maybe_json = _extract_json_object(llm_response)
        if maybe_json:
            try:
                parsed = json.loads(maybe_json)
            except Exception:
                parsed = None
        if parsed is None:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM response was not valid JSON: {llm_response[:1000]}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM response JSON was not an object")

    # Normalize and validate keys and types (tolerate minor deviations)
    found_raw = parsed.get("found", None)
    if isinstance(found_raw, bool):
        found_val = found_raw
    elif isinstance(found_raw, str):
        found_val = found_raw.strip().lower() in ("true", "yes", "1")
    elif isinstance(found_raw, (int, float)):
        found_val = bool(found_raw)
    else:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM JSON missing or invalid 'found' key")

    # value may be string or null; coerce common primitives to string
    val = parsed.get("value")
    if val is not None and not isinstance(val, str):
        if isinstance(val, (int, float, bool)):
            val = str(val)
        else:
            try:
                val = str(val)
            except Exception:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="'value' must be a string or null")

    explanation = parsed.get("explanation") or ""
    if not isinstance(explanation, str):
        explanation = str(explanation)

    evidence_raw = parsed.get("evidence_sentences")
    evidence: List[int] = []
    if evidence_raw is None:
        evidence = []
    elif isinstance(evidence_raw, list):
        for item in evidence_raw:
            if isinstance(item, int):
                evidence.append(item)
            elif isinstance(item, str):
                try:
                    evidence.append(int(item))
                except Exception:
                    # skip non-integer strings
                    continue
            else:
                # skip unsupported types
                continue
    else:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="'evidence_sentences' must be a list")

    # Normalize evidence tables/figures
    def _norm_int_list(v: Any) -> List[int]:
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
        # stable unique
        seen = set()
        uniq: List[int] = []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    evidence_tables = _norm_int_list(parsed.get("evidence_tables"))
    evidence_figures = _norm_int_list(parsed.get("evidence_figures"))

    # Build the stored JSON
    stored = {
        "found": found_val,
        "value": val,
        "explanation": explanation,
        "evidence_sentences": evidence,
        "evidence_tables": evidence_tables,
        "evidence_figures": evidence_figures,
        "llm_raw": llm_response[:4000],
    }

    # Persist under dynamic column name derived from parameter name
    col_name = snake_case_param(payload.parameter_name)

    try:
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col_name, stored, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    # Auto-fill human_param_* from llm_param_* if missing (never overwrite)
    try:
        col_human = col_name.replace("llm_param_", "human_param_", 1)
        human_payload = {
            **stored,
            "autofilled": True,
            "source": "llm",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        await run_in_threadpool(
            cits_dp_service.copy_jsonb_if_empty,
            citation_id,
            col_name,
            col_human,
            human_payload,
            table_name,
        )
    except Exception:
        pass

    return {"status": "success", "sr_id": sr_id, "citation_id": citation_id, "column": col_name, "extraction": stored}


@router.post("/{sr_id}/citations/{citation_id}/human-extract-parameter")
async def human_extract_parameter(
    sr_id: str,
    citation_id: int,
    payload: HumanParameterRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Persist a human-provided parameter value into the screening Postgres citations table
    under a dynamically created JSONB column derived from the parameter name. The column
    name is prefixed with 'human_param_' to distinguish from automated LLM-based extractions.
    Implementation mirrors extract_parameter_endpoint but accepts the human answer directly
    and does not call any LLM.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # Ensure citation exists (we won't require full_text for human input but check row presence)
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Normalize value
    val = payload.value
    if val is not None and not isinstance(val, str):
        try:
            val = str(val)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="'value' must be a string or null")

    # Normalize evidence_sentences
    evidence = payload.evidence_sentences or []
    if not isinstance(evidence, list) or not all(isinstance(i, int) for i in evidence):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="'evidence_sentences' must be a list of integers")

    explanation = payload.explanation or ""
    if not isinstance(explanation, str):
        explanation = str(explanation)

    # Build the stored JSON
    stored = {
        "found": bool(payload.found),
        "value": val,
        "explanation": explanation,
        "evidence_sentences": evidence,
        "human": True,
        "reviewer": payload.reviewer,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Derive human-prefixed column name from parameter name. Reuse snake_case_param then replace prefix.
    try:
        col_llm = snake_case_param(payload.parameter_name) if snake_case_param else None
    except Exception:
        col_llm = None

    if col_llm:
        col_name = col_llm.replace("llm_param_", "human_param_", 1)
    else:
        # fallback core name
        try:
            from ..services.cit_db_service import snake_case as _snake_case
            core = _snake_case(payload.parameter_name) if _snake_case else ""
        except Exception:
            core = ""
        col_name = f"human_param_{core}" if core else "human_param_param"

    try:
        updated = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, col_name, stored, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    return {"status": "success", "sr_id": sr_id, "citation_id": citation_id, "column": col_name, "extraction": stored}


@router.post("/{sr_id}/citations/{citation_id}/extract-fulltext")
async def extract_fulltext_from_storage(
    sr_id: str,
    citation_id: int,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Download the citation's stored PDF from object storage, run Grobid process_structure,
    build a numbered fulltext_str (like the Streamlit flow), save it into the citation row
    under column "fulltext", and return the generated fulltext_str.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    # fetch citation row
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # Determine storage path for the citation PDF
    storage_path = row.get("fulltext_url")
    if not storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No fulltext storage path found on citation row")

    try:
        content, _filename = await storage_service.get_bytes_by_path(storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fulltext file not found in storage")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unrecognized storage path format")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to download from storage: {e}")

    # If the citation row already contains an extracted full text in the "fulltext" column,
    # only use it if the stored md5 matches the pdf we just downloaded.
    cached_full_text = None
    if "fulltext" in row and row.get("fulltext"):
        cached_full_text = row.get("fulltext")

    # compute md5 of the current PDF bytes from storage
    current_md5 = hashlib.md5(content).hexdigest()
    stored_md5 = row.get("fulltext_md5")

    if cached_full_text and stored_md5 and current_md5 and stored_md5 == current_md5:
        return {
            "status": "success",
            "sr_id": sr_id,
            "citation_id": citation_id,
            "fulltext": cached_full_text,
            "n_pages": None,
            "cached": True,
        }

    # write to temp file and call grobid (+ Azure DI in parallel)
    tmp = NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()

        # process with grobid (sentence coords) and Azure DI (tables/figures) in parallel
        async def _run_grobid():
            return await grobid_service.process_structure(tmp.name)

        async def _run_docint():
            if not azure_docint_client or not azure_docint_client.is_available():
                return {"success": False, "error": "Azure DI not configured", "figures": [], "tables": []}
            return await azure_docint_client.extract_citation_artifacts(tmp.name, source_type="file")

        try:
            (coords, pages), docint_res = await asyncio.gather(
                _run_grobid(),
                _run_docint(),
            )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Fulltext processing failed: {e}")

        # filter sentence annotations
        annotations = [a for a in coords if a.get("type") == "s" and a.get("text")]
        full_text_arr = _list_set([a["text"] for a in annotations])
        full_text_str = "\n\n".join([f"[{i}] {x}" for i, x in enumerate(full_text_arr)])

        # -------------------------
        # Upload Azure DI artifacts
        # -------------------------
        fulltext_figures: List[Dict[str, Any]] = []
        fulltext_tables: List[Dict[str, Any]] = []
        artifact_coords: List[Dict[str, Any]] = []

        try:
            if docint_res and isinstance(docint_res, dict) and docint_res.get("success"):
                pages_meta = docint_res.get("pages") or []
                # Determine artifact base path from the fulltext_url directory
                # storage_path is "container/blob".
                container, blob = storage_path.split("/", 1)
                blob_dir = str(Path(blob).parent).replace("\\", "/")
                artifacts_prefix = f"{container}/{blob_dir}/{citation_id}_artifacts"
                artifacts_prefix = artifacts_prefix.replace("//", "/").rstrip("/")

                # Figures: write png
                for fig in (docint_res.get("figures") or []):
                    try:
                        idx = int(fig.get("index"))
                    except Exception:
                        continue
                    artifact_id = f"figure_{idx}.png"
                    blob_address = f"{artifacts_prefix}/{artifact_id}"
                    png_bytes = fig.get("png_bytes") or b""
                    caption = fig.get("caption")
                    bbox = fig.get("bounding_box")
                    boxes = normalize_bounding_regions_to_boxes(bbox, pages_meta)

                    # Upload only if we actually got image bytes
                    if png_bytes:
                        await storage_service.put_bytes_by_path(
                            blob_address,
                            png_bytes,
                            content_type="image/png",
                        )

                    fulltext_figures.append(
                        {
                            "blob_address": blob_address,
                            "caption": caption,
                            "bounding_box": boxes,
                            "description": None,
                            "index": idx,
                        }
                    )

                    # Also add to overlay coords so the existing PDF viewer logic can
                    # highlight tables/figures using the same shape as Grobid coords.
                    for b in boxes or []:
                        if not isinstance(b, dict):
                            continue
                        artifact_coords.append(
                            {
                                **b,
                                "type": "figure",
                                "artifact_index": idx,
                                "text": f"Figure F{idx}",
                            }
                        )

                # Tables: write markdown (.md)
                for tbl in (docint_res.get("tables") or []):
                    try:
                        idx = int(tbl.get("index"))
                    except Exception:
                        continue
                    artifact_id = f"table_{idx}.md"
                    blob_address = f"{artifacts_prefix}/{artifact_id}"
                    md = (tbl.get("table_markdown") or "").encode("utf-8")
                    caption = tbl.get("caption")
                    bbox = tbl.get("bounding_box")
                    boxes = normalize_bounding_regions_to_boxes(bbox, pages_meta)
                    if md:
                        await storage_service.put_bytes_by_path(
                            blob_address,
                            md,
                            content_type="text/markdown",
                        )
                    fulltext_tables.append(
                        {
                            "blob_address": blob_address,
                            "caption": caption,
                            "bounding_box": boxes,
                            "description": None,
                            "index": idx,
                        }
                    )

                    for b in boxes or []:
                        if not isinstance(b, dict):
                            continue
                        artifact_coords.append(
                            {
                                **b,
                                "type": "table",
                                "artifact_index": idx,
                                "text": f"Table T{idx}",
                            }
                        )
        except Exception:
            # Best-effort; DI artifacts should not block fulltext extraction.
            fulltext_figures = []
            fulltext_tables = []
            artifact_coords = []

    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    # persist full_text_str and coordinates/pages into citation row
    try:
        coords_for_overlay = list(annotations) + list(artifact_coords)
        updated1 = await run_in_threadpool(cits_dp_service.update_text_column, citation_id, "fulltext", full_text_str, table_name)
        updated2 = await run_in_threadpool(cits_dp_service.update_text_column, citation_id, "fulltext_md5", current_md5, table_name)
        updated3 = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, "fulltext_coords", coords_for_overlay, table_name)
        updated4 = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, "fulltext_pages", pages, table_name)
        updated5 = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, "fulltext_figures", fulltext_figures, table_name)
        updated6 = await run_in_threadpool(cits_dp_service.update_jsonb_column, citation_id, "fulltext_tables", fulltext_tables, table_name)
        updated = updated1 or updated2 or updated3 or updated4 or updated5 or updated6
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row with full text: {e}")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to update")

    return {
        "status": "success",
        "sr_id": sr_id,
        "citation_id": citation_id,
        "fulltext": full_text_str,
        "n_pages": len(pages),
        "fulltext_figures": fulltext_figures,
        "fulltext_tables": fulltext_tables,
    }
