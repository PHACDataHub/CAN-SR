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

from .config import settings


def _is_postgres_configured() -> bool:
    """
    Check if PostgreSQL is configured via the POSTGRES_MODE profile.
    """
    try:
        prof = settings.postgres_profile()
    except Exception:
        return False

    # minimal requirements
    if not (prof.get("database") and prof.get("user")):
        return False

    # password required for local/docker
    if prof.get("mode") in ("local", "docker") and not prof.get("password"):
        return False

    # azure requires host
    if prof.get("mode") == "azure" and not prof.get("host"):
        return False

    return True


async def load_sr_and_check(
    sr_id: str,
    current_user: Dict[str, Any],
    srdb_service,
    require_screening: bool = True,
    require_visible: bool = True,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[str]]:
    """
    Load a systematic review document and validate permissions.

    Args:
      sr_id: SR id string
      current_user: current user dict (must contain "id" and "email")
      srdb_service: SR DB service instance (must implement get_systematic_review and user_has_sr_permission)
      require_screening: if True, also ensure the SR has a configured screening_db and return its connection string
      require_visible: if True, require the SR 'visible' flag to be True; set False for endpoints like hard-delete

    Returns:
      (sr_doc, screening_obj or None)

    Raises HTTPException with appropriate status codes on failure so routers can just propagate.
    """

    # fetch SR
    try:
        sr = await run_in_threadpool(srdb_service.get_systematic_review, sr_id, not require_visible)
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
        has_perm = await run_in_threadpool(srdb_service.user_has_sr_permission, sr_id, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to check permissions: {e}")

    if not has_perm:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view/modify this systematic review")

    screening = sr.get("screening_db") if isinstance(sr, dict) else None
    if require_screening:
        if not screening:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screening database configured for this systematic review")


    return sr, screening
