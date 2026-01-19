"""
API endpoints for managing the Systematic Review GPT systems
"""

from typing import Dict, Any, Optional, List
import os
import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status,
)
from pydantic import BaseModel
import yaml

from ..core.config import settings
from ..core.security import get_current_active_user
from ..services.user_db import user_db as user_db_service
from ..services.sr_db_service import srdb_service
from ..core.cit_utils import load_sr_and_check

router = APIRouter()

# srdb_service provides higher-level helpers for systematic review DB operations
_ensure_db_available = srdb_service.ensure_db_available

class SystematicReviewCreate(BaseModel):
    name: str
    description: Optional[str] = None
    criteria_yaml: Optional[str] = None  # raw YAML string


class SystematicReviewRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    owner_id: str
    owner_email: str
    users: List[str]
    created_at: str
    updated_at: str
    # visibility flag - if False the SR is considered deleted/hidden
    visible: bool = True
    # raw parsed YAML mapping (keeps original structure)
    criteria: Optional[Dict[str, Any]] = None
    # raw YAML string
    criteria_yaml: Optional[str] = None
    # convenience structured metadata extracted from criteria (l1, l2, parameters)
    criteria_parsed: Optional[Dict[str, Any]] = None





@router.post("/create", response_model=SystematicReviewRead, status_code=status.HTTP_201_CREATED)
async def create_systematic_review(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    criteria_file: Optional[UploadFile] = File(None),
    criteria_yaml: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Create a new systematic review.

    Accepts:
    - name: display name for the SR (form field)
    - description: optional description
    - criteria_file: YAML file upload containing criteria (multipart/form-data)
    - criteria_yaml: raw YAML string (form field)

    One of criteria_file or criteria_yaml may be provided. If both are provided, criteria_file takes precedence.
    The created SR is stored in MongoDB and the creating user is added as the first member.
    """
    _ensure_db_available()

    if not name or not name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")

    # Load YAML criteria
    criteria_str: Optional[str] = None
    criteria_obj: Optional[Dict[str, Any]] = None

    try:
        if criteria_file:
            raw = await criteria_file.read()
            criteria_str = raw.decode("utf-8")
        elif criteria_yaml:
            criteria_str = criteria_yaml

        if criteria_str:
            criteria_obj = yaml.safe_load(criteria_str)
            # ensure it's a mapping/dict
            if criteria_obj is None:
                criteria_obj = {}
            elif not isinstance(criteria_obj, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parsed YAML criteria must be a mapping/object at the top level",
                )
    except yaml.YAMLError as ye:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid YAML provided: {ye}"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        sr_doc = await srdb_service.create_systematic_review(
            name=name,
            description=description,
            criteria_str=criteria_str,
            criteria_obj=criteria_obj,
            owner_id=current_user.get("id"),
            owner_email=current_user.get("email"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create systematic review: {e}")

    return SystematicReviewRead(
        id=sr_doc.get("_id"),
        name=sr_doc.get("name"),
        description=sr_doc.get("description"),
        owner_id=sr_doc.get("owner_id"),
        owner_email=sr_doc.get("owner_email"),
        users=sr_doc.get("users", []),
        created_at=sr_doc.get("created_at"),
        updated_at=sr_doc.get("updated_at"),
        visible=sr_doc.get("visible", True),
        criteria=sr_doc.get("criteria"),
        criteria_yaml=sr_doc.get("criteria_yaml"),
        criteria_parsed=sr_doc.get("criteria_parsed"),
    )


class AddUserRequest(BaseModel):
    user_email: Optional[str] = None
    user_id: Optional[str] = None


class RemoveUserRequest(BaseModel):
    user_email: Optional[str] = None
    user_id: Optional[str] = None


@router.post("/{sr_id}/add-user")
async def add_user_to_systematic_review(
    sr_id: str,
    payload: AddUserRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Add another user to an existing systematic review.

    Provide either user_email or user_id in the request body.
    Only users already present in the user registry can be added.
    The endpoint checks that the requester is a member of the SR.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    # resolve user
    target_user_id = None
    if payload.user_email:
        target_user_id = payload.user_email
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing data user_email")

    try:
        res = await srdb_service.add_user(sr_id, target_user_id, current_user.get("id"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to add user: {e}")

    return {"status": "success", "sr_id": sr_id, "added_user_id": target_user_id, "matched_count": res.get("matched_count"), "modified_count": res.get("modified_count")}


@router.post("/{sr_id}/remove-user")
async def remove_user_from_systematic_review(
    sr_id: str,
    payload: RemoveUserRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Remove a user from an existing systematic review.

    Provide either user_email or user_id in the request body.
    The endpoint checks that the requester is a member of the SR (or owner).
    The owner cannot be removed via this endpoint.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")
    
    # resolve user
    target_user_id = None
    if payload.user_email:
        target_user_id = payload.user_email
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing data user_email")

    # do not allow removing the owner
    if target_user_id == sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the owner from the systematic review")

    try:
        res = await srdb_service.remove_user(sr_id, target_user_id, current_user.get("id"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove user: {e}")

    return {"status": "success", "sr_id": sr_id, "removed_user_id": target_user_id, "matched_count": res.get("matched_count"), "modified_count": res.get("modified_count")}


@router.get("/mine", response_model=List[SystematicReviewRead])
async def list_systematic_reviews_for_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    List all systematic reviews the current user has access to (is a member of).
    Hidden/deleted SRs (visible == False) are excluded.
    """
    _ensure_db_available()

    user_id = current_user.get("email")
    results = []
    try:
        docs = await srdb_service.list_systematic_reviews_for_user(user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list systematic reviews: {e}")

    for doc in docs:
        results.append(
            SystematicReviewRead(
                id=doc.get("_id"),
                name=doc.get("name"),
                description=doc.get("description"),
                owner_id=doc.get("owner_id"),
                owner_email=doc.get("owner_email"),
                users=doc.get("users", []),
                created_at=doc.get("created_at"),
                updated_at=doc.get("updated_at"),
                visible=doc.get("visible", True),
                criteria=doc.get("criteria"),
                criteria_yaml=doc.get("criteria_yaml"),
                criteria_parsed=doc.get("criteria_parsed"),
            )
        )

    return results


@router.get("/{sr_id}", response_model=SystematicReviewRead)
async def get_systematic_review(sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)):
    """
    Get a single systematic review by id. User must be a member to view.
    """

    try:
        doc, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    return SystematicReviewRead(
        id=doc.get("_id"),
        name=doc.get("name"),
        description=doc.get("description"),
        owner_id=doc.get("owner_id"),
        owner_email=doc.get("owner_email"),
        users=doc.get("users", []),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        visible=doc.get("visible", True),
        criteria=doc.get("criteria"),
        criteria_yaml=doc.get("criteria_yaml"),
        criteria_parsed=doc.get("criteria_parsed"),
    )


@router.get("/{sr_id}/criteria_parsed")
async def get_systematic_review_criteria_parsed(
    sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Return the structured criteria_parsed object for the given systematic review.

    Permissions: caller must be a member of the SR (or the owner).
    Returns an empty dict if no parsed criteria are available.
    """

    try:
        doc, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    cp = doc.get("criteria_parsed") or {}
    return {"criteria_parsed": cp}


@router.put("/{sr_id}/criteria", response_model=SystematicReviewRead)
async def update_systematic_review_criteria(
    sr_id: str,
    criteria_file: Optional[UploadFile] = File(None),
    criteria_yaml: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Edit/update the criteria for an existing systematic review.

    Accepts either a YAML file upload (criteria_file) or a raw YAML string (criteria_yaml).
    The caller must already be a member of the systematic review (or the owner).
    The parsed criteria (dict) and the raw YAML are both saved to the SR document.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    # Load YAML criteria
    criteria_str: Optional[str] = None
    criteria_obj: Optional[Dict[str, Any]] = None

    try:
        if criteria_file:
            raw = await criteria_file.read()
            criteria_str = raw.decode("utf-8")
        elif criteria_yaml:
            criteria_str = criteria_yaml

        if not criteria_str:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either criteria_file or criteria_yaml must be provided")

        criteria_obj = yaml.safe_load(criteria_str)
        if criteria_obj is None:
            criteria_obj = {}
        elif not isinstance(criteria_obj, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parsed YAML criteria must be a mapping/object at the top level",
            )
    except yaml.YAMLError as ye:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid YAML provided: {ye}"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # perform update
    try:
        doc = await srdb_service.update_criteria(sr_id, criteria_obj, criteria_str, current_user.get("id"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update criteria: {e}")

    return SystematicReviewRead(
        id=doc.get("_id"),
        name=doc.get("name"),
        description=doc.get("description"),
        owner_id=doc.get("owner_id"),
        owner_email=doc.get("owner_email"),
        users=doc.get("users", []),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        visible=doc.get("visible", True),
        criteria=doc.get("criteria"),
        criteria_yaml=doc.get("criteria_yaml"),
        criteria_parsed=doc.get("criteria_parsed"),
    )


@router.delete("/{sr_id}")
async def delete_systematic_review(sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)):
    """
    Soft-delete a systematic review by marking its 'visible' flag as False.

    Only the owner may delete a systematic review.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    requester_id = current_user.get("id")
    if requester_id != sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may delete this systematic review")

    try:
        res = await srdb_service.soft_delete_systematic_review(sr_id, requester_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete systematic review: {e}")

    return {"status": "success", "sr_id": sr_id, "deleted": True, "matched_count": res.get("matched_count"), "modified_count": res.get("modified_count")}


@router.post("/{sr_id}/undelete")
async def undelete_systematic_review(sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)):
    """
    Undelete (restore) a systematic review by marking its 'visible' flag as True.

    Only the owner may undelete a systematic review.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False, require_visible=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    requester_id = current_user.get("id")
    if requester_id != sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may undelete this systematic review")

    try:
        res = await srdb_service.undelete_systematic_review(sr_id, requester_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to undelete systematic review: {e}")

    return {"status": "success", "sr_id": sr_id, "undeleted": True, "matched_count": res.get("matched_count"), "modified_count": res.get("modified_count")}


@router.delete("/{sr_id}/hard")
async def hard_delete_systematic_review(sr_id: str, current_user: Dict[str, Any] = Depends(get_current_active_user)):
    """
    Permanently remove the systematic review document from MongoDB.

    This now attempts to clean up associated screening resources (Postgres DB + stored fulltexts)
    by calling the screening cleanup helper in the citations router before deleting the SR doc.

    Only the owner may perform a hard delete.
    """

    try:
        sr, screening, db_conn = await load_sr_and_check(sr_id, current_user, _ensure_db_available, srdb_service, require_screening=False, require_visible=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load systematic review: {e}")

    requester_id = current_user.get("id")
    if requester_id != sr.get("owner_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may hard-delete this systematic review")

    # Attempt to perform screening resources cleanup prior to deleting the SR document.
    cleanup_result = None
    try:
        # import inside function to avoid circular imports at module load time
        from ..citations.router import hard_delete_screening_resources as _hard_delete_screening_resources  # type: ignore

        try:
            cleanup_result = await _hard_delete_screening_resources(sr_id, current_user)
        except HTTPException:
            # propagate HTTPExceptions from cleanup (e.g., permission or config issues)
            raise
        except Exception as e:
            # non-fatal: capture error and continue with SR deletion
            cleanup_result = {"status": "cleanup_error", "error": str(e)}
    except Exception as e:
        # If import fails, record that cleanup couldn't be run and continue
        cleanup_result = {"status": "cleanup_import_failed", "error": str(e)}

    try:
        res = await srdb_service.hard_delete_systematic_review(sr_id, requester_id)
        deleted_count = res.get("deleted_count")
        if not deleted_count:
            # If backend reported zero deletions, raise NotFound to match prior behavior
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found during hard delete")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to hard-delete systematic review: {e}")

    return {
        "status": "success",
        "sr_id": sr_id,
        "hard_deleted": True,
        "deleted_count": deleted_count,
        "screening_cleanup": cleanup_result,
    }
