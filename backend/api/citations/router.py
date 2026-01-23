"""
Screening router - handles upload of citation CSVs for title/abstract (L1) screening.

Behavior:
- All endpoints require a Systematic Review (sr_id) that the user is a member of (re-uses checks from manage.router).
- Uploading a CSV will:
  - Parse the CSV
  - Create a new Postgres database (requires POSTGRES_ADMIN_DSN env var)
  - Create a `citations` table with columns based on the "include" list from the criteria YAML
  - Insert citation rows from the CSV into the table
  - Save connection information for the created DB into the Systematic Review Mongo document
Notes:
- This implementation uses blocking psycopg2 calls dispatched into a threadpool with run_in_threadpool.
- It is defensive: if required env vars or psycopg2 are missing it returns HTTP 503 with an actionable message.
"""

from typing import Dict, Any, List, Optional
import os
import time
import csv
import io
import re
from datetime import datetime
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import yaml
import psycopg2
import psycopg2.extras


from ..services.sr_db_service import srdb_service

from ..core.security import get_current_active_user
from ..core.config import settings
from ..services.cit_db_service import cits_dp_service, snake_case, parse_dsn
from ..core.cit_utils import load_sr_and_check

router = APIRouter()


class UploadResult(BaseModel):
    sr_id: str
    db_name: str
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


def _create_db_and_table_sync(admin_dsn: str, db_name: str, columns: List[str], rows: List[Dict[str, Any]]) -> int:
    # Delegate to consolidated postgres service
    return cits_dp_service.create_db_and_table_sync(admin_dsn, db_name, columns, rows)


@router.post("/{sr_id}/upload-csv", response_model=UploadResult)
async def upload_screening_csv(
    sr_id: str,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Upload a CSV of citations for title/abstract screening and create a dedicated Postgres DB/table.

    Requirements:
    - Environment variable POSTGRES_ADMIN_DSN must be set and point to a Postgres server where the service has permission to CREATE DATABASE.
    - The YAML criteria include list (manage/configs/criteria_config_measles_updated.yaml) is used to determine columns to create.
    - The SR must exist and the user must be a member of the SR (or owner).
    """

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, _ = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    # Check admin DSN (use centralized settings)
    admin_dsn = settings.POSTGRES_URI
    if not admin_dsn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Postgres admin DSN not configured. Set POSTGRES_ADMIN_DSN or DATABASE_URL in configuration/environment.",
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

    # Build a database name
    safe_sr = re.sub(r"[^0-9a-zA-Z_]", "_", sr_id)
    timestamp = int(time.time())
    db_name = f"sr_{safe_sr}_{timestamp}"

    # Create DB, table and insert rows in threadpool
    try:
        inserted = await run_in_threadpool(_create_db_and_table_sync, admin_dsn, db_name, include_columns, normalized_rows)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create database/table or insert rows: {e}")

    # Save DB connection metadata into SR Mongo doc
    try:
        parsed = _parse_dsn(admin_dsn)
        # construct a connection string for the new DB (do not alter credentials - reuse admin DSN but point to DB)
        if "://" in admin_dsn:
            import urllib.parse as up

            p = up.urlparse(admin_dsn)
            new_path = "/" + db_name
            new_p = p._replace(path=new_path)
            db_conn = up.urlunparse(new_p)
        else:
            if "dbname=" in admin_dsn:
                db_conn = re.sub(r"dbname=[^ ]+", f"dbname={db_name}", admin_dsn)
            else:
                db_conn = f"{admin_dsn} dbname={db_name}"

        screening_info = {
            "screening_db": {
                "db_name": db_name,
                "connection_string": db_conn,
                "created_at": datetime.utcnow().isoformat(),
                "rows": inserted,
            }
        }

        # Update SR document with screening DB info using PostgreSQL
        await run_in_threadpool(
            srdb_service.update_screening_db_info,
            settings.POSTGRES_URI,
            sr_id,
            screening_info["screening_db"]
        )
    except Exception as e:
        # DB succeeded but saving metadata failed - surface warning but allow API to succeed with caution
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database created ({db_name}) but failed to update Systematic Review entry: {e}")

    return UploadResult(
        sr_id=sr_id,
        db_name=db_name,
        rows_inserted=inserted,
        message=f"Created screening DB '{db_name}' and inserted {inserted} rows",
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
    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    if not screening:
        return {"citation_ids": []}

    try:
        ids = await run_in_threadpool(cits_dp_service.list_citation_ids, db_conn, filter_step)
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id))
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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review or screening: {e}")

    if not screening:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screening database configured for this systematic review")

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id))
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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
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
    # Verify citation exists BEFORE uploading blob to storage
    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id))
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")
    try:
        existing_row = await run_in_threadpool(cits_dp_service.get_citation_by_id, db_conn, int(citation_id))
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to query screening DB: {e}")

    if not existing_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

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
        updated = await run_in_threadpool(cits_dp_service.attach_fulltext, db_conn, citation_id, storage_path, content)
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
    Delete the screening Postgres database and all associated fulltext files
    for the given systematic review.

    This should be called prior to permanently deleting the SR document so
    that the screening DB and stored fulltexts are cleaned up.

    Requirements:
    - Caller must be the SR owner.
    - POSTGRES_ADMIN_DSN or DATABASE_URL must be configured in settings.
    """

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, db_conn_str, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    requester_id = current_user.get("id")
    if requester_id != sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may perform screening cleanup for this systematic review")

    if not screening:
        return {"status": "no_screening_db", "message": "No screening DB configured for this SR", "deleted_db": False, "deleted_files": 0}

    db_conn = screening.get("connection_string")
    if not db_conn:
        return {"status": "no_screening_db", "message": "Incomplete screening DB metadata", "deleted_db": False, "deleted_files": 0}

    admin_dsn = settings.POSTGRES_ADMIN_DSN or settings.DATABASE_URL
    if not admin_dsn:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Postgres admin DSN not configured. Set POSTGRES_ADMIN_DSN or DATABASE_URL in configuration/environment.")

    # 1) collect fulltext URLs from the screening DB
    try:
        urls = await run_in_threadpool(cits_dp_service.list_fulltext_urls, db_conn)
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
                # fallback: try direct deletion via blob client (best-effort)
                if storage_service:
                    try:
                        blob_client = storage_service.blob_service_client.get_blob_client(container=container, blob=blob)
                        blob_client.delete_blob()
                        deleted_files += 1
                    except Exception:
                        failed_files += 1
                else:
                    failed_files += 1
    except Exception as e:
        # non-fatal; proceed to drop DB but report file deletion failures
        pass

    # 3) drop the screening database
    try:
        await run_in_threadpool(cits_dp_service.drop_database, admin_dsn, db_name)
        db_dropped = True
    except RuntimeError as rexc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to drop screening DB: {e}")

    # 4) remove screening_db metadata from SR document
    try:
        await run_in_threadpool(
            srdb_service.clear_screening_db_info,
            settings.POSTGRES_URI,
            sr_id
        )
    except Exception:
        # non-fatal, but report it
        pass

    return {
        "status": "success",
        "sr_id": sr_id,
        "deleted_db": db_dropped,
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

    db_conn_str = settings.POSTGRES_URI
    try:
        sr, screening, db_conn = await load_sr_and_check(
            sr_id, current_user, db_conn_str, srdb_service
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    if not screening or not db_conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No screening database configured for this systematic review",
        )

    try:
        csv_bytes = await run_in_threadpool(cits_dp_service.dump_citations_csv, db_conn)
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
