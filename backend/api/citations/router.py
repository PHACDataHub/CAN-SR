"""Screening citations router.

This router handles upload of citation CSVs for title/abstract (L1) screening.

Behavior:
- All endpoints require a Systematic Review (sr_id) that the user is a member of.
- Uploading a CSV will:
  - Parse the CSV
  - Create a new Postgres *table* in the shared database
  - Insert citation rows from the CSV into that table
  - Save the table name + connection string into the Systematic Review record

We intentionally avoid creating a new Postgres database per upload.
"""

from typing import Dict, Any, List, Optional
import os
import time
import csv
import io
import re
from datetime import datetime
import pandas as pd
import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..services.sr_db_service import srdb_service

from ..core.security import get_current_active_user
from ..core.config import settings
from ..services.cit_db_service import cits_dp_service, snake_case, snake_case_column, parse_dsn
from ..core.cit_utils import load_sr_and_check

router = APIRouter()


def _is_undefined_table_error(exc: Exception) -> bool:
    """Best-effort detection for missing Postgres table errors."""
    try:
        # psycopg2 raises UndefinedTable for missing relations.
        import psycopg2

        if isinstance(exc, psycopg2.errors.UndefinedTable):
            return True
        # Some errors come wrapped; fall back to message sniffing.
        msg = str(exc).lower()
        return "does not exist" in msg and "relation" in msg
    except Exception:
        return False


def _is_postgres_configured() -> bool:
    """
    Check if PostgreSQL is configured via the POSTGRES_MODE profile.
    """
    try:
        prof = settings.postgres_profile()
    except Exception:
        return False

    if not (prof.get("database") and prof.get("user")):
        return False

    if prof.get("mode") in ("local", "docker") and not prof.get("password"):
        return False

    if prof.get("mode") == "azure" and not prof.get("host"):
        return False

    return True


class UploadResult(BaseModel):
    sr_id: str
    table_name: str
    rows_inserted: int
    message: str
    created_at: str

def _load_include_columns_from_criteria(sr_doc: Optional[Dict[str, Any]] = None) -> List[str]:
    # Delegate to consolidated postgres service
    try:
        return cits_dp_service.load_include_columns_from_criteria(sr_doc)
    except Exception:
        return []
def _parse_dsn(dsn: str) -> Dict[str, str]:
    # Delegate to consolidated postgres service
    try:
        return parse_dsn(dsn)
    except Exception:
        return {}
def _create_table_and_insert_sync(table_name: str, columns: List[str], rows: List[Dict[str, Any]]) -> int:
    return cits_dp_service.create_table_and_insert_sync(table_name, columns, rows)


@router.post("/{sr_id}/upload-csv", response_model=UploadResult)
async def upload_screening_csv(
    sr_id: str,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Upload a CSV of citations for title/abstract screening and create a dedicated Postgres table.

    Requirements:
    - Postgres must be configured via POSTGRES_MODE and POSTGRES_* env vars.
    - The SR must exist and the user must be a member of the SR (or owner).
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    # Check admin config (use centralized settings)
    if not _is_postgres_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Postgres not configured. Set POSTGRES_MODE and POSTGRES_* env vars.",
        )

    # Read CSV content
    include_columns = None
    try:
        csv_reader = pd.read_csv(file.file)
        normalized_rows = csv_reader.to_dict(orient='records')
        include_columns = csv_reader.columns
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to parse CSV: {e}")

    # Use all CSV headers as the columns for the screening DB (preserve original CSV headers)
    if len(include_columns) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No columns found to create screening table")

    # Build a unique table name for this upload
    safe_sr = re.sub(r"[^0-9a-zA-Z_]", "_", sr_id)
    timestamp = int(time.time())
    # keep within 63 chars: prefix + '_' + ts + '_citations'
    table_name = f"sr_{safe_sr}_{timestamp}_cit"

    # If replacing, best-effort drop previous table (if any)
    try:
        old = (sr.get("screening_db") or {}).get("table_name")
        if old:
            await run_in_threadpool(cits_dp_service.drop_table, old)
    except Exception:
        # best-effort only
        pass

    # Create table and insert rows in threadpool
    try:
        inserted = await run_in_threadpool(_create_table_and_insert_sync, table_name, include_columns, normalized_rows)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create table or insert rows: {e}")

    # Save DB connection metadata into SR Mongo doc
    try:
        screening_info = {
            "screening_db": {
                "table_name": table_name,
                "created_at": datetime.utcnow().isoformat(),
                "rows": inserted,
            }
        }

        # Update SR document with screening DB info using PostgreSQL
        await run_in_threadpool(
            srdb_service.update_screening_db_info,
            sr_id,
            screening_info["screening_db"]
        )
    except Exception as e:
        # DB succeeded but saving metadata failed - surface warning but allow API to succeed with caution
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Table created ({table_name}) but failed to update Systematic Review entry: {e}")

    return UploadResult(
        sr_id=sr_id,
        table_name=table_name,
        rows_inserted=inserted,
        message=f"Created screening table '{table_name}' and inserted {inserted} rows",
        created_at=datetime.utcnow().isoformat(),
    )


# Helper to list citation ids - delegated to core.postgres.list_citation_ids
# The blocking implementation lives in backend.api.core.postgres.list_citation_ids


@router.get("/{sr_id}/citations")
async def list_citation_ids(
    sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user), filter_step: Optional[str] = None,
):
    """
    List all citation ids for the systematic review's screening database.

    Returns a simple list of integers (the 'id' primary key from the citations table).
    """
    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    if not screening:
        return {"citation_ids": []}

    table_name = (screening or {}).get("table_name") or "citations"

    # Ensure decision columns are never stale before filtering.
    # Validation strategy: UI filters by human_l1_decision / human_l2_decision.
    try:
        cp = (sr or {}).get("criteria_parsed") or (sr or {}).get("criteria") or {}
        await run_in_threadpool(cits_dp_service.backfill_human_decisions, cp, table_name)
    except Exception:
        # best-effort; listing should still work even if backfill fails
        pass

    try:
        ids = await run_in_threadpool(cits_dp_service.list_citation_ids, filter_step, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        # If the SR points at a screening table that no longer exists (e.g. dropped),
        # treat it as "no citations" instead of poisoning the shared connection.
        if _is_undefined_table_error(e):
            return {"citation_ids": []}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    return {"citation_ids": ids}


# Helper to get citation row by id - delegated to backend.api.core.postgres.get_citation_by_id


@router.get("/{sr_id}/citations/{citation_id}")
async def get_citation_by_id(
    sr_id: str,
    citation_id: int,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Get full citation data for a given citation id from the SR's screening DB.

    Permissions: user must be a member of the SR or the owner.
    Returns: a JSON object representing the citation row (keys are DB column names).
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    table_name = (screening or {}).get("table_name") or "citations"

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    return row


# API model + helper to build a combined citation string from selected columns
class CombinedRequest(BaseModel):
    include_columns: Optional[List[str]] = None


def _build_combined_citation_from_row(row: Dict[str, Any], include_columns: List[str]) -> str:
    # Delegate to consolidated postgres service
    return cits_dp_service.build_combined_citation_from_row(row, include_columns)


@router.post("/{sr_id}/citations/{citation_id}/combined")
async def build_combined_citation(
    sr_id: str,
    citation_id: int,
    payload: CombinedRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Build a combined citation string for a single citation row.

    Body (optional):
      {
        "include_columns": ["Title", "Authors", "Year"]
      }

    If include_columns is omitted, the endpoint will attempt to load the L1 include list
    from the SR's parsed criteria (or fallback project config). The returned string uses
    the format "<ColumnName>: <value>  \\n" for each included column, in the order provided.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    if not screening:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screening database configured for this systematic review")

    table_name = (screening or {}).get("table_name") or "citations"

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # As a final fallback, use all columns present in include columns
    data = []
    for k in row.keys():
        if k not in payload.include_columns:
            continue
        # Convert snake_case DB name back to a more human header (replace _ with space and title-case)
        data.append(k)

    combined = _build_combined_citation_from_row(row, data)
    return {"sr_id": sr_id, "citation_id": citation_id, "combined_citation": combined}


# Helper to update citation fulltext - delegated to backend.api.core.postgres.update_citation_fulltext


@router.post("/{sr_id}/citations/{citation_id}/upload-fulltext")
async def upload_citation_fulltext(
    sr_id: str,
    citation_id: int,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Upload a full-text PDF for a specific citation and attach the storage path to the citation row.

    Behavior:
    - Verifies the caller is a member (or owner) of the SR
    - Uploads the file to the same storage service used by /api/files
    - Updates the screening Postgres "citations" table row setting the "fulltext_url" column
      to the storage path (container/blob).
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    # Validate file
    if not file or not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is required")

    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    # Prefer PDFs but allow other types if necessary; restrict to .pdf here
    if ext != ".pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are accepted for full text upload")

    content = await file.read()
    new_md5 = hashlib.md5(content).hexdigest() if content is not None else ""
    # Verify citation exists BEFORE uploading blob to storage
    table_name = (screening or {}).get("table_name") or "citations"

    try:
        existing_row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not existing_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    # If the PDF changed (md5 differs), clear L2 screening answers + parameter extractions + fulltext artifacts.
    # (Do NOT clear L1 answers.)
    try:
        existing_md5 = (existing_row or {}).get("fulltext_md5") or ""
        existing_url = (existing_row or {}).get("fulltext_url") or ""

        pdf_changed = False
        if existing_md5 and new_md5 and existing_md5 != new_md5:
            pdf_changed = True
        # Legacy: if we had a PDF but no md5 recorded, treat upload as replacement.
        if not existing_md5 and existing_url:
            pdf_changed = True

        if pdf_changed:
            # Clear fulltext extraction columns (they will be regenerated later)
            await run_in_threadpool(
                cits_dp_service.clear_columns,
                citation_id,
                [
                    "fulltext",
                    "fulltext_coords",
                    "fulltext_pages",
                    "fulltext_figures",
                    "fulltext_tables",
                    "fulltext_md5",
                ],
                table_name,
            )

            # Clear all parameter extraction columns
            await run_in_threadpool(
                cits_dp_service.clear_columns_by_prefix,
                citation_id,
                ["llm_param_", "human_param_"],
                table_name,
            )

            # Clear L2 screening columns only
            # NOTE (validation): we do not use l2_screen for filtering; keep it untouched/non-authoritative.
            cols_to_clear = ["llm_l2_decision", "human_l2_decision"]
            try:
                cp = (sr or {}).get("criteria_parsed") or (sr or {}).get("criteria") or {}
                l2 = cp.get("l2") if isinstance(cp, dict) else None
                l2_questions = (l2 or {}).get("questions") if isinstance(l2, dict) else None
                if isinstance(l2_questions, list):
                    for q in l2_questions:
                        try:
                            llm_col = snake_case_column(q)
                        except Exception:
                            llm_col = None
                        try:
                            core = snake_case(q, max_len=56)
                            human_col = f"human_{core}" if core else "human_col"
                        except Exception:
                            human_col = None

                        if llm_col:
                            cols_to_clear.append(llm_col)
                        if human_col:
                            cols_to_clear.append(human_col)
            except Exception:
                # best-effort
                pass

            await run_in_threadpool(cits_dp_service.clear_columns, citation_id, cols_to_clear, table_name)
    except Exception:
        # Best-effort; do not block upload.
        pass

    # Upload to storage service (reuse storage logic from files.router)
    try:
        from ..services.storage import storage_service
    except Exception:
        storage_service = None

    if not storage_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage service not available")

    # Upload file for the current user
    document_id = await storage_service.upload_user_document(
        user_id=current_user["id"],
        filename=file.filename,
        file_content=content,
    )

    if not document_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload file to storage service")
    # Build storage path (container + blob name) so it can be stored in Postgres
    # Note: storage.py stores blobs at users/{user_id}/documents/{doc_id}_{filename}
    blob_name = f"users/{current_user['id']}/documents/{document_id}_{file.filename}"
    container = storage_service.container_name
    storage_path = f"{container}/{blob_name}"

    # Update citation row in Postgres
    try:
        updated = await run_in_threadpool(cits_dp_service.attach_fulltext, citation_id, storage_path, content, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update citation row: {e}")
    if not updated:
        # If the citation id doesn't exist, consider rolling back the uploaded file (best effort)
        # Attempt to delete the uploaded blob (best-effort; not fatal if it fails)
        try:
            await storage_service.delete_user_document(current_user["id"], document_id, file.filename)
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found to attach fulltext file")
    return {
        "status": "success",
        "sr_id": sr_id,
        "citation_id": citation_id,
        "storage_path": storage_path,
        "document_id": document_id,
    }


# Helper to list fulltext URLs - delegated to backend.api.core.postgres.list_fulltext_urls


# Helper to drop a database - delegated to backend.api.core.postgres.drop_database
async def hard_delete_screening_resources(sr_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Delete the screening Postgres table and all associated fulltext files
    for the given systematic review.

    This should be called prior to permanently deleting the SR document so
    that the screening DB and stored fulltexts are cleaned up.

    Requirements:
    - Caller must be the SR owner.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    requester_id = current_user.get("id")
    if requester_id != sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may perform screening cleanup for this systematic review")

    if not screening:
        return {"status": "no_screening_db", "message": "No screening table configured for this SR", "deleted_table": False, "deleted_files": 0}

    table_name = screening.get("table_name")
    if not table_name:
        return {"status": "no_screening_db", "message": "Incomplete screening DB metadata", "deleted_table": False, "deleted_files": 0}

    # 1) collect fulltext URLs from the screening DB
    try:
        urls = await run_in_threadpool(cits_dp_service.list_fulltext_urls, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB for fulltext URLs: {e}")

    # 2) delete blobs for each url (best-effort)
    deleted_files = 0
    failed_files = 0
    try:
        try:
            from ..services.storage import storage_service
        except Exception:
            storage_service = None

        for u in urls:
            if not u:
                continue
            # expect format "container/blob_path"
            if "/" in u:
                container, blob = u.split("/", 1)
            else:
                # unrecognised format, skip
                failed_files += 1
                continue

            # prefer to use storage_service.delete_user_document when we can parse user/doc/filename
            parsed_ok = False
            if storage_service:
                try:
                    # blob expected: users/{user_id}/documents/{doc_id}_{filename}
                    if blob.startswith("users/"):
                        parts = blob.split("/")
                        # expect ["users", user_id, "documents", "{doc_id}_{filename}"]
                        if len(parts) >= 4 and parts[2] == "documents":
                            user_id = parts[1]
                            doc_part = "/".join(parts[3:])  # handle any extra slashes in filename
                            # split first underscore to get doc_id and filename
                            if "_" in doc_part:
                                doc_id, filename = doc_part.split("_", 1)
                                # call delete_user_document (async)
                                try:
                                    ok = await storage_service.delete_user_document(user_id, doc_id, filename)
                                    if ok:
                                        deleted_files += 1
                                    else:
                                        failed_files += 1
                                    parsed_ok = True
                                except Exception:
                                    failed_files += 1
                                    parsed_ok = True
                except Exception:
                    parsed_ok = False

            if not parsed_ok:
                # fallback: delete by storage path (works for both azure/local)
                if storage_service:
                    try:
                        await storage_service.delete_by_path(f"{container}/{blob}")
                        deleted_files += 1
                    except FileNotFoundError:
                        failed_files += 1
                    except Exception:
                        failed_files += 1
                else:
                    failed_files += 1
    except Exception as e:
        # non-fatal; proceed to drop DB but report file deletion failures
        pass

    # 3) drop the screening table
    try:
        await run_in_threadpool(cits_dp_service.drop_table, table_name)
        table_dropped = True
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to drop screening table: {e}")

    # 4) remove screening_db metadata from SR document
    try:
        await run_in_threadpool(
            srdb_service.clear_screening_db_info,
            sr_id
        )
    except Exception:
        # non-fatal, but report it
        pass

    return {
        "status": "success",
        "sr_id": sr_id,
        "deleted_table": table_dropped,
        "deleted_files": deleted_files,
        "failed_file_deletions": failed_files,
    }


# Optional endpoint to trigger the cleanup directly
@router.post("/{sr_id}/hard-clean")
async def hard_clean_screening_endpoint(sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)):
    result = await hard_delete_screening_resources(sr_id, current_user)
    return result


@router.get("/{sr_id}/export-citations")
async def export_citations_csv(
    sr_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """Download an exact CSV dump of the SR's Postgres `citations` table.

    Notes:
    - Auth: requires the requester to be a member/owner of the SR (load_sr_and_check)
    - Filename: set to a generic default; frontend proxy/UI may override via its own
      Content-Disposition.
    """

    try:
        sr, screening = await load_sr_and_check(
            sr_id, current_user, srdb_service
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    if not screening:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No screening database configured for this systematic review",
        )

    table_name = (screening or {}).get("table_name") or "citations"

    try:
        # Validation-friendly export: exclude fulltext/artifacts and flatten JSON columns.
        csv_bytes = await run_in_threadpool(cits_dp_service.dump_citations_csv_filtered, table_name)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export citations CSV: {e}",
        )

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="sr_{sr_id}_citations.csv"'
        },
    )
