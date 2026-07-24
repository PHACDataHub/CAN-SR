"""
API endpoints for managing the Systematic Review GPT systems
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import yaml
from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import status
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from pydantic import ValidationError

from ..core.cit_utils import load_sr_and_check
from ..core.config import settings
from ..core.security import get_current_active_user
from ..criteria.models import CriteriaConfigV2
from ..criteria.service import criteria_configuration_service
from ..services.citation_field_service import discover_citation_fields
from ..services.sr_db_service import srdb_service
from ..services.user_db import user_db_service

router = APIRouter()


class CriteriaConfigSaveRequest(BaseModel):
    expected_revision: int
    force: bool = False
    migration_fingerprint: str | None = None
    criteria: CriteriaConfigV2


class CriteriaYamlImportRequest(BaseModel):
    criteria_yaml: str


def _criteria_error(exc: ValueError) -> HTTPException:
    if isinstance(exc, ValidationError):
        errors = [
            {
                'path': list(error['loc']),
                'code': error['type'],
                'message': error['msg'],
            }
            for error in exc.errors(include_url=False)
        ]
    else:
        errors = [
            {'path': [], 'code': 'invalid_criteria', 'message': str(exc)},
        ]
    return HTTPException(status_code=422, detail={'errors': errors})


def _require_migration_confirmation(result, fingerprint: str | None) -> None:
    if result.source_format == 'legacy_yaml_v1' and result.requires_confirmation:
        if fingerprint != result.fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    'code': 'migration_confirmation_required',
                    'message': 'Preview and confirm the legacy migration before saving.',
                    'fingerprint': result.fingerprint,
                },
            )


class SystematicReviewCreate(BaseModel):
    name: str
    description: str | None = None
    criteria_yaml: str | None = None  # raw YAML string


class SystematicReviewRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    owner_id: str
    owner_email: str
    users: list[str]
    created_at: str
    updated_at: str
    # visibility flag - if False the SR is considered deleted/hidden
    visible: bool = True
    # raw parsed YAML mapping (keeps original structure)
    criteria: dict[str, Any] | None = None
    # raw YAML string
    criteria_yaml: str | None = None
    # convenience structured metadata extracted from criteria (l1, l2, parameters)
    criteria_parsed: dict[str, Any] | None = None
    # screening table metadata used by the setup page to detect existing imported citations
    screening_db: dict[str, Any] | None = None

    # Per-step, per-criterion thresholds (SR-scoped). Example:
    # {
    #   "l1": {"population": 0.9, "intervention": 0.85},
    #   "l2": {"outcome": 0.9}
    # }
    screening_thresholds: dict[str, Any] | None = None

    # SR-scoped per-step per-criterion additions injected into CRITICAL prompts.
    # Shape:
    # {
    #   "l1": {"criterion_key": "..."},
    #   "l2": {"criterion_key": "..."}
    # }
    critical_prompt_additions: dict[str, Any] | None = None


@router.post('/create', response_model=SystematicReviewRead, status_code=status.HTTP_201_CREATED)
async def create_systematic_review(
    name: str = Form(...),
    description: str | None = Form(None),
    criteria_file: UploadFile | None = File(None),
    criteria_yaml: str | None = Form(None),
    migration_fingerprint: str | None = Form(None),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    Create a new systematic review.

    Accepts:
    - name: display name for the SR (form field)
    - description: optional description
    - criteria_file: YAML file upload containing criteria (multipart/form-data)
    - criteria_yaml: raw YAML string (form field)

    One of criteria_file or criteria_yaml may be provided. If both are provided, criteria_file takes precedence.
    The created SR is stored in PostgreSQL and the creating user is added as the first member.
    """

    if not name or not name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='name is required',
        )

    # Load YAML criteria
    criteria_str: str | None = None
    criteria_obj: dict[str, Any] | None = None

    try:
        if criteria_file:
            raw = await criteria_file.read()
            criteria_str = raw.decode('utf-8')
        elif criteria_yaml:
            criteria_str = criteria_yaml

        if criteria_str:
            normalized = criteria_configuration_service.parse_yaml(
                criteria_str,
            )
            _require_migration_confirmation(normalized, migration_fingerprint)
            criteria_obj = normalized.criteria.model_dump(
                mode='json', exclude_none=True,
            )
            criteria_str = criteria_configuration_service.export_yaml(
                normalized.criteria,
            )
    except (yaml.YAMLError, ValueError) as exc:
        raise _criteria_error(exc) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e),
        )

    try:
        sr_doc = await run_in_threadpool(
            srdb_service.create_systematic_review,
            name,
            description,
            criteria_str,
            criteria_obj,
            current_user.get('id'),
            current_user.get('email'),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create systematic review: {e}",
        )

    return SystematicReviewRead(
        id=sr_doc.get('id'),
        name=sr_doc.get('name'),
        description=sr_doc.get('description'),
        owner_id=sr_doc.get('owner_id'),
        owner_email=sr_doc.get('owner_email'),
        users=sr_doc.get('users', []),
        created_at=sr_doc.get('created_at'),
        updated_at=sr_doc.get('updated_at'),
        visible=sr_doc.get('visible', True),
        criteria=sr_doc.get('criteria'),
        criteria_yaml=sr_doc.get('criteria_yaml'),
        criteria_parsed=sr_doc.get('criteria_parsed'),
        screening_db=sr_doc.get('screening_db'),
        screening_thresholds=sr_doc.get('screening_thresholds'),
        critical_prompt_additions=sr_doc.get('critical_prompt_additions'),
    )


class AddUserRequest(BaseModel):
    user_email: str | None = None
    user_id: str | None = None


class RemoveUserRequest(BaseModel):
    user_email: str | None = None
    user_id: str | None = None


@router.post('/{sr_id}/add-user')
async def add_user_to_systematic_review(
    sr_id: str,
    payload: AddUserRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    Add another user to an existing systematic review.

    Provide either user_email or user_id in the request body.
    Only users already present in the user registry can be added.
    The endpoint checks that the requester is a member of the SR.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    # resolve user
    target_user_id = None
    if payload.user_email:
        target_user_id = payload.user_email
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Missing data user_email',
        )

    try:
        res = await run_in_threadpool(srdb_service.add_user, sr_id, target_user_id, current_user.get('id'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to add user: {e}",
        )

    return {'status': 'success', 'sr_id': sr_id, 'added_user_id': target_user_id, 'matched_count': res.get('matched_count'), 'modified_count': res.get('modified_count')}


@router.post('/{sr_id}/remove-user')
async def remove_user_from_systematic_review(
    sr_id: str,
    payload: RemoveUserRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    Remove a user from an existing systematic review.

    Provide either user_email or user_id in the request body.
    The endpoint checks that the requester is a member of the SR (or owner).
    The owner cannot be removed via this endpoint.
    """
    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    # resolve user
    target_user_id = None
    if payload.user_email:
        target_user_id = payload.user_email
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Missing data user_email',
        )

    # do not allow removing the owner
    if target_user_id == sr.get('owner_id'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot remove the owner from the systematic review',
        )

    try:
        res = await run_in_threadpool(srdb_service.remove_user, sr_id, target_user_id, current_user.get('id'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove user: {e}",
        )

    return {'status': 'success', 'sr_id': sr_id, 'removed_user_id': target_user_id, 'matched_count': res.get('matched_count'), 'modified_count': res.get('modified_count')}


@router.get('/mine', response_model=list[SystematicReviewRead])
async def list_systematic_reviews_for_user(
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    List all systematic reviews the current user has access to (is a member of).
    Hidden/deleted SRs (visible == False) are excluded.
    """

    user_id = current_user.get('email')
    results = []
    try:
        docs = await run_in_threadpool(srdb_service.list_systematic_reviews_for_user, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list systematic reviews: {e}",
        )

    for doc in docs:
        results.append(
            SystematicReviewRead(
                id=doc.get('id'),
                name=doc.get('name'),
                description=doc.get('description'),
                owner_id=doc.get('owner_id'),
                owner_email=doc.get('owner_email'),
                users=doc.get('users', []),
                created_at=doc.get('created_at'),
                updated_at=doc.get('updated_at'),
                visible=doc.get('visible', True),
                criteria=doc.get('criteria'),
                criteria_yaml=doc.get('criteria_yaml'),
                criteria_parsed=doc.get('criteria_parsed'),
                screening_db=doc.get('screening_db'),
                screening_thresholds=doc.get('screening_thresholds'),
                critical_prompt_additions=doc.get('critical_prompt_additions'),
            ),
        )

    return results


async def _load_criteria_review(sr_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
    review, _screening = await load_sr_and_check(
        sr_id, current_user, srdb_service, require_screening=False,
    )
    return review


@router.get('/{sr_id}/citation-fields')
async def get_citation_fields(
    sr_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    review = await _load_criteria_review(sr_id, current_user)
    return await run_in_threadpool(discover_citation_fields, review)


@router.get('/{sr_id}/criteria-config')
async def get_criteria_config(
    sr_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    review = await _load_criteria_review(sr_id, current_user)
    try:
        if isinstance(review.get('criteria'), dict):
            result = criteria_configuration_service.normalize(
                review['criteria'],
            )
        elif review.get('criteria_yaml'):
            result = criteria_configuration_service.parse_yaml(
                review['criteria_yaml'], source_kind='backend_load',
            )
        else:
            raise ValueError(
                'No usable criteria configuration is stored for this review.',
            )
    except ValueError as exc:
        raise _criteria_error(exc) from exc

    response: dict[str, Any] = {
        'criteria': result.criteria.model_dump(mode='json', exclude_none=True),
        'revision': review.get('criteria_revision', 0),
        'warnings': [item.model_dump(mode='json') for item in result.diagnostics],
    }
    if result.source_format == 'legacy_yaml_v1':
        response['migration'] = {
            'status': 'preview',
            'source_format': result.source_format,
            'fingerprint': result.fingerprint,
            'requires_confirmation': result.requires_confirmation,
            'stats': result.stats.model_dump() if result.stats else None,
            'diagnostics': [item.model_dump(mode='json') for item in result.diagnostics],
        }
    return response


@router.post('/{sr_id}/criteria-config/validate')
async def validate_criteria_config(
    sr_id: str,
    criteria: CriteriaConfigV2,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    await _load_criteria_review(sr_id, current_user)
    return {
        'valid': True,
        'criteria': criteria.model_dump(mode='json', exclude_none=True),
        'warnings': [],
    }


@router.post('/{sr_id}/criteria-config/import-yaml')
async def import_criteria_yaml(
    sr_id: str,
    payload: CriteriaYamlImportRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    await _load_criteria_review(sr_id, current_user)
    try:
        result = criteria_configuration_service.parse_yaml(
            payload.criteria_yaml,
        )
    except ValueError as exc:
        raise _criteria_error(exc) from exc
    return result.model_dump(mode='json', exclude_none=True)


@router.put('/{sr_id}/criteria-config')
async def save_criteria_config(
    sr_id: str,
    payload: CriteriaConfigSaveRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    review = await _load_criteria_review(sr_id, current_user)
    if (review.get('screening_db') or {}).get('table_name') and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='This SR already has screening data. Pass force=true to confirm criteria invalidation.',
        )
    try:
        stored = criteria_configuration_service.normalize(review['criteria'])
    except (KeyError, ValueError):
        stored = None
    if stored:
        _require_migration_confirmation(stored, payload.migration_fingerprint)
    criteria = payload.criteria.model_dump(mode='json', exclude_none=True)
    criteria_yaml = criteria_configuration_service.export_yaml(
        payload.criteria,
    )
    saved = await run_in_threadpool(
        srdb_service.save_criteria_config,
        sr_id,
        criteria,
        criteria_yaml,
        payload.expected_revision,
        current_user.get('email') or current_user.get('id'),
    )
    return {
        'criteria': criteria,
        'revision': saved['revision'],
        'warnings': [],
        'invalidation': {'forced': payload.force, 'screening_data_present': bool(review.get('screening_db'))},
    }


@router.get('/{sr_id}/criteria-config/export-yaml', response_class=PlainTextResponse)
async def export_criteria_yaml(
    sr_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    response = await get_criteria_config(sr_id, current_user)
    return PlainTextResponse(
        criteria_configuration_service.export_yaml(response['criteria']),
        media_type='application/yaml',
        headers={
            'Content-Disposition': f'attachment; filename="criteria-{sr_id}.yaml"',
        },
    )


@router.get('/{sr_id}', response_model=SystematicReviewRead)
async def get_systematic_review(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """
    Get a single systematic review by id. User must be a member to view.
    """

    try:
        doc, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    return SystematicReviewRead(
        id=doc.get('id'),
        name=doc.get('name'),
        description=doc.get('description'),
        owner_id=doc.get('owner_id'),
        owner_email=doc.get('owner_email'),
        users=doc.get('users', []),
        created_at=doc.get('created_at'),
        updated_at=doc.get('updated_at'),
        visible=doc.get('visible', True),
        criteria=doc.get('criteria'),
        criteria_yaml=doc.get('criteria_yaml'),
        criteria_parsed=doc.get('criteria_parsed'),
        screening_db=doc.get('screening_db'),
        screening_thresholds=doc.get('screening_thresholds'),
        critical_prompt_additions=doc.get('critical_prompt_additions'),
    )


@router.get('/{sr_id}/criteria_parsed')
async def get_systematic_review_criteria_parsed(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    Return the structured criteria_parsed object for the given systematic review.

    Permissions: caller must be a member of the SR (or the owner).
    Returns an empty dict if no parsed criteria are available.
    """

    try:
        doc, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    cp = doc.get('criteria_parsed') or {}
    return {'criteria_parsed': cp}


@router.put('/{sr_id}/criteria', response_model=SystematicReviewRead)
async def update_systematic_review_criteria(
    sr_id: str,
    criteria_file: UploadFile | None = File(None),
    criteria_yaml: str | None = Form(None),
    force: str | None = Form(None),
    migration_fingerprint: str | None = Form(None),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """
    Edit/update the criteria for an existing systematic review.

    Accepts either a YAML file upload (criteria_file) or a raw YAML string (criteria_yaml).
    The caller must already be a member of the systematic review (or the owner).
    The parsed criteria (dict) and the raw YAML are both saved to the SR document.

    If the SR already has a screening table (citations have been uploaded), the update
    is blocked unless force=true is provided. This prevents accidental invalidation of
    existing screening data.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    # Guard: block criteria update if screening data already exists (unless force=true)
    existing_table = (sr.get('screening_db') or {}).get('table_name')
    force_flag = str(force).lower().strip() in (
        'true', '1', 'yes',
    ) if force else False
    if existing_table and not force_flag:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='This SR already has screening data. Updating criteria may invalidate existing screening results. Pass force=true to confirm.',
        )

    # Load YAML criteria
    criteria_str: str | None = None
    criteria_obj: dict[str, Any] | None = None

    try:
        if criteria_file:
            raw = await criteria_file.read()
            criteria_str = raw.decode('utf-8')
        elif criteria_yaml:
            criteria_str = criteria_yaml

        if not criteria_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Either criteria_file or criteria_yaml must be provided',
            )

        normalized = criteria_configuration_service.parse_yaml(criteria_str)
        _require_migration_confirmation(normalized, migration_fingerprint)
        criteria_obj = normalized.criteria.model_dump(
            mode='json', exclude_none=True,
        )
        criteria_str = criteria_configuration_service.export_yaml(
            normalized.criteria,
        )
    except (yaml.YAMLError, ValueError) as exc:
        raise _criteria_error(exc) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e),
        )

    # perform update
    try:
        doc = await run_in_threadpool(srdb_service.update_criteria, sr_id, criteria_obj, criteria_str, current_user.get('id'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update criteria: {e}",
        )

    return SystematicReviewRead(
        id=doc.get('id'),
        name=doc.get('name'),
        description=doc.get('description'),
        owner_id=doc.get('owner_id'),
        owner_email=doc.get('owner_email'),
        users=doc.get('users', []),
        created_at=doc.get('created_at'),
        updated_at=doc.get('updated_at'),
        visible=doc.get('visible', True),
        criteria=doc.get('criteria'),
        criteria_yaml=doc.get('criteria_yaml'),
        criteria_parsed=doc.get('criteria_parsed'),
        screening_db=doc.get('screening_db'),
        screening_thresholds=doc.get('screening_thresholds'),
        critical_prompt_additions=doc.get('critical_prompt_additions'),
    )


class ThresholdsUpdateRequest(BaseModel):
    screening_thresholds: dict[str, Any] = {}


class CriticalPromptAdditionsUpdateRequest(BaseModel):
    critical_prompt_additions: dict[str, Any] = {}


@router.get('/{sr_id}/screening_thresholds')
async def get_screening_thresholds(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """Get SR-scoped per-step per-criterion thresholds."""

    try:
        doc, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    thresholds = doc.get('screening_thresholds') or {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    return {'sr_id': sr_id, 'screening_thresholds': thresholds}


@router.put('/{sr_id}/screening_thresholds')
async def update_screening_thresholds(
    sr_id: str,
    payload: ThresholdsUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Update SR-scoped per-step per-criterion thresholds.

    Any SR member may update thresholds (per product requirement).
    """

    try:
        _doc, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    thresholds = payload.screening_thresholds or {}
    if not isinstance(thresholds, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='screening_thresholds must be an object',
        )

    # Normalize: only allow known steps keys, but keep it permissive.
    normalized: dict[str, Any] = {}
    for step in ('l1', 'l2'):
        block = thresholds.get(step)
        if isinstance(block, dict):
            out: dict[str, float] = {}
            for k, v in block.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                try:
                    f = float(v)
                except Exception:
                    continue
                f = max(0.0, min(1.0, f))
                out[k] = f
            normalized[step] = out
        else:
            normalized[step] = {}

    await run_in_threadpool(srdb_service.update_screening_thresholds, sr_id, normalized)
    return {'status': 'success', 'sr_id': sr_id, 'screening_thresholds': normalized}


@router.get('/{sr_id}/critical_prompt_additions')
async def get_critical_prompt_additions(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """Get SR-scoped per-step per-criterion critical prompt additions."""

    try:
        doc, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    cpa = doc.get('critical_prompt_additions') or {}
    if not isinstance(cpa, dict):
        cpa = {}
    return {'sr_id': sr_id, 'critical_prompt_additions': cpa}


@router.put('/{sr_id}/critical_prompt_additions')
async def update_critical_prompt_additions(
    sr_id: str,
    payload: CriticalPromptAdditionsUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Update SR-scoped per-step per-criterion critical prompt additions.

    Any SR member may update these (mirrors thresholds permissions).
    """

    try:
        _doc, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    cpa = payload.critical_prompt_additions or {}
    if not isinstance(cpa, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='critical_prompt_additions must be an object',
        )

    normalized: dict[str, Any] = {}
    for step in ('l1', 'l2'):
        block = cpa.get(step)
        if isinstance(block, dict):
            out: dict[str, str] = {}
            for k, v in block.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if v is None:
                    out[k] = ''
                else:
                    out[k] = str(v)
            normalized[step] = out
        else:
            normalized[step] = {}

    await run_in_threadpool(srdb_service.update_critical_prompt_additions, sr_id, normalized)
    return {'status': 'success', 'sr_id': sr_id, 'critical_prompt_additions': normalized}


@router.delete('/{sr_id}')
async def delete_systematic_review(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """
    Soft-delete a systematic review by marking its 'visible' flag as False.

    Only the owner may delete a systematic review.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    requester_id = current_user.get('id')
    if requester_id != sr.get('owner_id'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Only the owner may delete this systematic review',
        )

    try:
        res = await run_in_threadpool(srdb_service.soft_delete_systematic_review, sr_id, requester_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete systematic review: {e}",
        )

    return {'status': 'success', 'sr_id': sr_id, 'deleted': True, 'matched_count': res.get('matched_count'), 'modified_count': res.get('modified_count')}


@router.post('/{sr_id}/undelete')
async def undelete_systematic_review(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """
    Undelete (restore) a systematic review by marking its 'visible' flag as True.

    Only the owner may undelete a systematic review.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False, require_visible=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    requester_id = current_user.get('id')
    if requester_id != sr.get('owner_id'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Only the owner may undelete this systematic review',
        )

    try:
        res = await run_in_threadpool(srdb_service.undelete_systematic_review, sr_id, requester_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to undelete systematic review: {e}",
        )

    return {'status': 'success', 'sr_id': sr_id, 'undeleted': True, 'matched_count': res.get('matched_count'), 'modified_count': res.get('modified_count')}


@router.delete('/{sr_id}/hard')
async def hard_delete_systematic_review(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    """
    Permanently remove the systematic review document from MongoDB.

    This now attempts to clean up associated screening resources (Postgres DB + stored fulltexts)
    by calling the screening cleanup helper in the citations router before deleting the SR doc.

    Only the owner may perform a hard delete.
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False, require_visible=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    requester_id = current_user.get('id')
    if requester_id != sr.get('owner_id'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Only the owner may hard-delete this systematic review',
        )

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
            cleanup_result = {'status': 'cleanup_error', 'error': str(e)}
    except Exception as e:
        # If import fails, record that cleanup couldn't be run and continue
        cleanup_result = {'status': 'cleanup_import_failed', 'error': str(e)}

    try:
        res = await run_in_threadpool(srdb_service.hard_delete_systematic_review, sr_id, requester_id)
        deleted_count = res.get('deleted_count')
        if not deleted_count:
            # If backend reported zero deletions, raise NotFound to match prior behavior
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Systematic review not found during hard delete',
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to hard-delete systematic review: {e}",
        )

    return {
        'status': 'success',
        'sr_id': sr_id,
        'hard_deleted': True,
        'deleted_count': deleted_count,
        'screening_cleanup': cleanup_result,
    }
