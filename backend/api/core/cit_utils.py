"""
Utility helpers for citations & systematic review routers.

This module centralizes common SR + screening checks used across multiple routers:
- ensure DB available
- fetch SR doc
- permission check (membership/owner)
- optional screening config and connection string extraction

Routers should call load_sr_and_check(...) to avoid duplicating this logic.
"""
from typing import Any, Dict, Optional, Tuple
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool

async def load_sr_and_check(
    sr_id: str,
    current_user: Dict[str, Any],
    db_conn_str: str,
    srdb_service,
    require_screening: bool = True,
    require_visible: bool = True,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[str]]:
    """
    Load a systematic review document and validate permissions.

    Args:
      sr_id: SR id string
      current_user: current user dict (must contain "id" and "email")
      db_conn_str: PostgreSQL connection string
      srdb_service: SR DB service instance (must implement get_systematic_review and user_has_sr_permission)
      require_screening: if True, also ensure the SR has a configured screening_db and return its connection string
      require_visible: if True, require the SR 'visible' flag to be True; set False for endpoints like hard-delete

    Returns:
      (sr_doc, screening_obj or None, db_conn_string or None)

    Raises HTTPException with appropriate status codes on failure so routers can just propagate.
    """
    # ensure DB helper present and call it
    if not db_conn_str:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfiguration: PostgreSQL connection not available",
        )
    try:
        await run_in_threadpool(srdb_service.ensure_db_available, db_conn_str)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    # fetch SR
    try:
        sr = await run_in_threadpool(srdb_service.get_systematic_review, db_conn_str, sr_id, not require_visible)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch systematic review: {e}")

    if not sr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

    if require_visible and not sr.get("visible", True):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

    # permission check (user must be member or owner)
    user_id = current_user.get("email")
    try:
        has_perm = await run_in_threadpool(srdb_service.user_has_sr_permission, db_conn_str, sr_id, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to check permissions: {e}")

    if not has_perm:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view/modify this systematic review")

    screening = sr.get("screening_db") if isinstance(sr, dict) else None
    db_conn = None
    if require_screening:
        if not screening:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screening database configured for this systematic review")
        db_conn = screening.get("connection_string")
        if not db_conn:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Screening DB connection info missing")

    return sr, screening, db_conn
