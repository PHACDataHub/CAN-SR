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
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

try:
    import rispy  # type: ignore
except Exception:  # pragma: no cover
    rispy = None

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import Response, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..services.sr_db_service import srdb_service

from ..core.security import get_current_active_user
from ..core.config import settings
from ..services.cit_db_service import cits_dp_service, snake_case, snake_case_column, parse_dsn
from ..services.citation_export_service import citation_export_service, ExportValidationError
from ..services.citation_import_preview_service import CitationImportPreviewService
from ..services.citation_import_service import citation_import_service
from ..services.citation_workspace_preferences_service import citation_workspace_preferences_service
from ..services.citation_deduplication_preferences_service import citation_deduplication_preferences_service
from ..services.citation_deduplication_service import recompute_affected_duplicate_groups
from ..services.citation_duplicate_review_service import citation_duplicate_review_service
from ..services.citation_duplicate_run_service import citation_duplicate_run_service
from ..services.storage import storage_service
from ..criteria.context import resolve_source_value
from .export_models import CitationExportRequest, CitationExportSchema
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
        return 'does not exist' in msg and 'relation' in msg
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

    if not (prof.get('database') and prof.get('user')):
        return False

    if prof.get('mode') in ('local', 'docker') and not prof.get('password'):
        return False

    if prof.get('mode') == 'azure' and not prof.get('host'):
        return False

    return True


class UploadResult(BaseModel):
    sr_id: str
    table_name: str
    rows_inserted: int
    message: str
    created_at: str


class CitationImportPreviewResponse(BaseModel):
    id: str
    source_format: str
    source_sha256: str
    schema_fingerprint: str
    proposed_mapping: dict[str, str | None]
    validation_report: dict[str, Any]
    staging_expires_at: str


class CitationImportPreviewCancelResponse(BaseModel):
    id: str
    cancelled: bool
    staging_cleanup_pending: bool


class CitationImportPreviewInspectionResponse(BaseModel):
    id: str
    citation_table_name: str | None
    source_sha256: str
    schema_fingerprint: str
    proposed_mapping: dict[str, str | None]
    validation_report: dict[str, Any]
    staging_expires_at: str
    created_at: str


class CitationImportPreviewCommitRequest(BaseModel):
    approved_mapping: dict[str, str | None]


class CitationImportPreviewMappingUpdateRequest(BaseModel):
    approved_mapping: dict[str, str | None]
    excluded_source_columns: list[str]
    excluded_ambiguous_row_numbers: list[int] = []


class CitationImportPreviewMappingUpdateResponse(BaseModel):
    id: str
    proposed_mapping: dict[str, str | None]
    mapping_decision: dict[str, Any]
    validation_report: dict[str, Any]


class CitationImportPreviewCommitResponse(BaseModel):
    id: str
    batch_id: str
    idempotent: bool
    inserted_count: int
    existing_exact_match_count: int
    invalid_count: int


class CitationImportResponse(BaseModel):
    sr_id: str
    table_name: str
    batch_id: str
    idempotent: bool
    rows_inserted: int
    invalid_count: int
    warnings: list[str] = []
    duplicates_skipped: int = 0
    rows_merged: int = 0


class CitationWorkspaceColumnsRequest(BaseModel):
    columns: list[str]


class SetAnswerRequest(BaseModel):
    item_type: str
    item_id: str
    source_column: str


def _criteria_config_items(sr: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    criteria = sr.get('criteria') or sr.get('criteria_parsed') or {}
    if not isinstance(criteria, dict):
        return [], []

    def items(stage: str) -> list[dict[str, Any]]:
        value = criteria.get(stage) or []
        if isinstance(value, dict):
            value = value.get('items') or []
        return [item for item in value if isinstance(item, dict)]

    return items('l1'), items('l2')


def _parameter_items(sr: dict[str, Any]) -> list[dict[str, Any]]:
    criteria = sr.get('criteria') or sr.get('criteria_parsed') or {}
    parameters = criteria.get('parameters') if isinstance(
        criteria, dict,
    ) else []
    if isinstance(parameters, dict):
        parameters = parameters.get('items') or []
    return [item for item in (parameters or []) if isinstance(item, dict)]


def _set_answer_payload(value: Any, item_type: str, screening_step: str) -> dict[str, Any]:
    value = str(value).strip()
    provenance = 'retrospective_validation'
    timestamp = datetime.utcnow().isoformat() + 'Z'
    if item_type == 'parameter':
        return {
            'found': True,
            'value': value,
            'explanation': '',
            'evidence_sentences': [],
            'human': True,
            'reviewer': None,
            'source': provenance,
            'timestamp': timestamp,
        }
    return {
        'selected': value,
        'explanation': '',
        'confidence': None,
        'human': True,
        'reviewer': None,
        'source': provenance,
        'timestamp': timestamp,
        'screening_step': screening_step,
        'pipeline': 'fulltext' if screening_step == 'l2' else 'title_abstract',
    }


def _set_answer_destinations(item_type: str, core: str) -> list[str]:
    if item_type == 'parameter':
        return [f'human_param_{core}']
    if item_type == 'l1':
        return [f'human_l1_{core}', f'human_l2_{core}']
    return [f'human_l2_{core}']


@router.post('/{sr_id}/set-answer')
async def set_answer(
    sr_id: str,
    payload: SetAnswerRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Copy a configured retrospective citation field into human answer fields."""
    item_type = payload.item_type.strip().lower()
    if item_type not in {'l1', 'l2', 'parameter'}:
        raise HTTPException(
            status_code=400, detail='item_type must be l1, l2, or parameter',
        )
    source_column = payload.source_column.strip()
    if not source_column:
        raise HTTPException(
            status_code=400, detail='source_column is required',
        )

    sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    l1_items, l2_items = _criteria_config_items(sr)
    parameter_items = _parameter_items(sr)
    if item_type == 'parameter':
        item = next(
            (
                i for i in parameter_items if str(
                    i.get('id'),
                ) == payload.item_id
            ), None,
        )
        stage = 'parameter'
    else:
        items = l1_items if item_type == 'l1' else l2_items
        item = next(
            (
                i for i in items if str(
                    i.get('id'),
                ) == payload.item_id
            ), None,
        )
        stage = item_type
    if not item:
        raise HTTPException(
            status_code=404, detail='Configured item not found',
        )
    if item.get('answer_column') != source_column:
        raise HTTPException(
            status_code=409, detail='source_column does not match the configured answer column',
        )

    item_name = item.get(
        'name',
    ) if item_type == 'parameter' else item.get('question')
    core = snake_case(
        str(item_name or ''),
        max_len=52 if item_type == 'parameter' else 56,
    )
    if not core:
        raise HTTPException(
            status_code=400, detail='Configured item has no usable name',
        )
    destinations = _set_answer_destinations(item_type, core)

    table_name = (screening or {}).get('table_name') or 'citations'
    try:
        columns = await run_in_threadpool(cits_dp_service.get_table_columns, table_name)
        available_columns = {
            str(column.get('column_name'))
            for column in columns
        }
        if source_column not in available_columns:
            raise HTTPException(
                status_code=400, detail=f"Source citation field '{source_column}' was not found",
            )
        citation_ids = await run_in_threadpool(cits_dp_service.list_citation_ids, None, table_name)
        rows = await run_in_threadpool(
            cits_dp_service.get_citations_by_ids,
            citation_ids,
            table_name,
            [
                'id', source_column,
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f'Failed to query screening DB: {exc}',
        )

    processed = copied = blank = 0
    for row in rows:
        processed += 1
        value = row.get(source_column)
        if value is None or (isinstance(value, str) and not value.strip()):
            blank += 1
            continue
        answer = _set_answer_payload(value, item_type, stage)
        for destination in destinations:
            await run_in_threadpool(
                cits_dp_service.update_jsonb_column, int(
                    row['id'],
                ), destination, answer, table_name,
            )
        copied += 1

    return {
        'status': 'success', 'item_type': item_type, 'item_id': payload.item_id,
        'processed': processed, 'copied': copied, 'blank': blank,
        'destinations': destinations,
    }


@router.post('/{sr_id}/import-previews', response_model=CitationImportPreviewResponse)
async def create_citation_import_preview(
    sr_id: str,
    file: UploadFile = File(...),
    commit_key: str = Form(...),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Parse and encrypt-stage an import; this endpoint never mutates citations."""
    sr, _screening = await load_sr_and_check(
        sr_id, current_user, srdb_service, require_screening=False,
    )
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='File is required',
        )
    try:
        raw_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Failed to read upload: {exc}',
        )
    if len(raw_bytes) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail='Uploaded file is too large',
        )
    citation_table_name = (sr.get('screening_db') or {}).get('table_name')
    try:
        service = CitationImportPreviewService(
            storage_service, secret_key=settings.SECRET_KEY,
            ttl_minutes=settings.CITATION_IMPORT_PREVIEW_TTL_MINUTES,
        )
        return await service.create(
            sr_id=sr_id, citation_table_name=citation_table_name, filename=file.filename,
            raw_bytes=raw_bytes, commit_key=commit_key, actor_id=current_user.get(
                'email',
            ) or current_user.get('id'),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to create import preview: {exc}',
        )


@router.post('/{sr_id}/imports', response_model=CitationImportResponse)
async def import_citations(
    sr_id: str,
    file: UploadFile = File(...),
    commit_key: str = Form(...),
    title_header: str | None = Form(None),
    abstract_header: str | None = Form(None),
    include_duplicates: bool = Form(False),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Parse and append a citation file immediately, retaining batch provenance."""
    sr, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='File is required',
        )

    try:
        raw = await file.read()
        if not raw:
            raise ValueError('Uploaded file is empty')
        max_bytes = int(getattr(settings, 'MAX_FILE_SIZE', 0) or 0)
        if max_bytes and len(raw) > max_bytes:
            raise ValueError(
                f'Uploaded file exceeds the {max_bytes} byte limit',
            )
        from ..services.citation_import_preview_service import build_preview
        parsed = build_preview(file.filename, raw)
        result = await run_in_threadpool(
            citation_import_service.append_rows_sync,
            sr_id=sr_id,
            table_name=(sr.get('screening_db') or {}).get('table_name'),
            source_format=parsed['source_format'],
            filename=file.filename,
            raw_bytes=raw,
            rows=parsed['normalized_rows'],
            source_columns=parsed['validation_report']['source_columns'],
            actor_id=current_user.get('email') or current_user.get('id'),
            commit_key=commit_key,
            title_header=title_header,
            abstract_header=abstract_header,
            include_duplicates=include_duplicates,
        )
        if not result['idempotent'] and not (sr.get('screening_db') or {}).get('table_name'):
            await run_in_threadpool(
                srdb_service.update_screening_db_info, sr_id, {
                    'table_name': result['table_name'], 'created_at': datetime.utcnow().isoformat(),
                    'rows': result['rows_inserted'],
                },
            )
        return CitationImportResponse(sr_id=sr_id, **result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to import citations: {exc}',
        )


@router.post('/{sr_id}/duplicates/check')
async def check_citation_duplicates(
    sr_id: str,
    file: UploadFile = File(...),
    title_header: str | None = Form(None),
    abstract_header: str | None = Form(None),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Count duplicate rows for upload UI feedback without inserting anything."""
    sr, _screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='File is required',
        )
    try:
        raw = await file.read()
        from ..services.citation_import_preview_service import build_preview
        parsed = build_preview(file.filename, raw)
        count = await run_in_threadpool(
            citation_import_service.count_duplicates_sync,
            sr_id=sr_id,
            table_name=(sr.get('screening_db') or {}).get('table_name'),
            rows=parsed['normalized_rows'],
            source_columns=parsed['validation_report']['source_columns'],
            title_header=title_header,
            abstract_header=abstract_header,
        )
        return {'duplicates_count': count}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )


@router.get('/{sr_id}/import-previews/{preview_id}', response_model=CitationImportPreviewInspectionResponse)
async def inspect_citation_import_preview(
    sr_id: str,
    preview_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Return active owned preview metadata without exposing staged file contents."""
    await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    try:
        service = CitationImportPreviewService(
            storage_service, secret_key=settings.SECRET_KEY,
            ttl_minutes=settings.CITATION_IMPORT_PREVIEW_TTL_MINUTES,
        )
        return service.inspect(
            preview_id=preview_id, sr_id=sr_id,
            actor_id=current_user.get('email') or current_user.get('id'),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to inspect import preview: {exc}',
        )


@router.put('/{sr_id}/import-previews/{preview_id}/mapping', response_model=CitationImportPreviewMappingUpdateResponse)
async def update_citation_import_preview_mapping(
    sr_id: str,
    preview_id: str,
    payload: CitationImportPreviewMappingUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Persist an active owner's mapping decision without mutating citation tables."""
    await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    try:
        service = CitationImportPreviewService(
            storage_service, secret_key=settings.SECRET_KEY,
            ttl_minutes=settings.CITATION_IMPORT_PREVIEW_TTL_MINUTES,
        )
        return await service.update_mapping(
            preview_id=preview_id, sr_id=sr_id,
            actor_id=current_user.get('email') or current_user.get('id'),
            approved_mapping=payload.approved_mapping,
            excluded_source_columns=payload.excluded_source_columns,
            excluded_ambiguous_row_numbers=payload.excluded_ambiguous_row_numbers,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to update import preview mapping: {exc}',
        )


@router.post('/{sr_id}/import-previews/{preview_id}/commit', response_model=CitationImportPreviewCommitResponse)
async def commit_citation_import_preview(
    sr_id: str,
    preview_id: str,
    payload: CitationImportPreviewCommitRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Commit an owned preview through the transactional import-batch workflow."""
    await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    try:
        service = CitationImportPreviewService(
            storage_service, secret_key=settings.SECRET_KEY,
            ttl_minutes=settings.CITATION_IMPORT_PREVIEW_TTL_MINUTES,
        )
        return await service.commit(
            preview_id=preview_id, sr_id=sr_id,
            actor_id=current_user.get('email') or current_user.get('id'),
            approved_mapping=payload.approved_mapping,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to commit import preview: {exc}',
        )


@router.delete('/{sr_id}/import-previews/{preview_id}', response_model=CitationImportPreviewCancelResponse)
async def cancel_citation_import_preview(
    sr_id: str,
    preview_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Cancel an authorized user's uncommitted import preview."""
    await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    try:
        service = CitationImportPreviewService(
            storage_service, secret_key=settings.SECRET_KEY,
            ttl_minutes=settings.CITATION_IMPORT_PREVIEW_TTL_MINUTES,
        )
        return await service.cancel(
            preview_id=preview_id, sr_id=sr_id,
            actor_id=current_user.get('email') or current_user.get('id'),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to cancel import preview: {exc}',
        )


def _sniff_citations_format(filename: str, raw_bytes: bytes) -> str:
    """Detect citations upload format.

    Returns:
      - "csv" for CSV
      - "ris" for RIS

    Rules:
      - .csv => csv
      - .ris/.txt => ris
      - Otherwise sniff content for RIS markers
    """

    name = (filename or '').lower()
    if name.endswith('.csv'):
        return 'csv'
    if name.endswith('.ris') or name.endswith('.txt'):
        return 'ris'

    try:
        text = raw_bytes.decode('utf-8', errors='ignore')
    except Exception:
        text = ''

    # Minimal RIS sniffing: many RIS files contain TY  - ... and ER  -
    if 'ty  -' in text.lower() and 'er  -' in text.lower():
        return 'ris'
    return 'csv'


def _join_list(v: Any, sep: str = '; ') -> str:
    if v is None:
        return ''
    if isinstance(v, list):
        return sep.join([str(x) for x in v if x is not None and str(x).strip() != '']).strip()
    return str(v)


def _extract_year(v: Any) -> str:
    if v is None:
        return ''
    s = str(v)
    m = re.search(r'(19|20)\d{2}', s)
    return m.group(0) if m else ''


def _ris_value_for_include(include_col: str, entry: dict[str, Any]) -> Any:
    """Map a requested include column name (human header) to rispy normalized keys."""

    key = (include_col or '').strip().lower()

    # Common include names in our configs
    if key == 'title':
        return entry.get('title') or entry.get('primary_title') or entry.get('short_title')
    if key == 'abstract':
        return entry.get('abstract') or entry.get('notes_abstract') or _join_list(entry.get('notes'), '\n')
    if key == 'keywords':
        return _join_list(entry.get('keywords'))
    if key == 'journal':
        return (
            entry.get('secondary_title')
            or entry.get('journal_name')
            or entry.get('alternate_title1')
            or entry.get('alternate_title2')
            or entry.get('alternate_title3')
        )
    if key == 'type':
        return entry.get('type_of_reference')
    if key in ('type of work', 'type_of_work'):
        return entry.get('type_of_work')
    if key == 'notes':
        return _join_list(entry.get('notes'), '\n')
    if key == 'year':
        return (
            _extract_year(entry.get('year'))
            or _extract_year(entry.get('publication_year'))
            or _extract_year(entry.get('date'))
        )

    # If someone configures include columns to rispy keys directly, support that too.
    # Example: include: ["authors", "doi"]
    v = entry.get(key)
    if isinstance(v, list):
        return _join_list(v)
    return v


def _parse_citations_csv_bytes(raw_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        text = raw_bytes.decode('utf-8-sig')
    except Exception:
        text = raw_bytes.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    cols = reader.fieldnames or []
    return rows, cols


def _parse_citations_ris_bytes(raw_bytes: bytes, include_columns: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    if not rispy:
        raise RuntimeError('RIS upload requested but rispy is not installed')

    try:
        text = raw_bytes.decode('utf-8-sig')
    except Exception:
        text = raw_bytes.decode('utf-8', errors='replace')

    entries = rispy.load(io.StringIO(text))
    if not entries:
        return [], include_columns

    normalized_rows: list[dict[str, Any]] = []
    for e in entries:
        row: dict[str, Any] = {}
        for col in include_columns:
            try:
                row[col] = _ris_value_for_include(col, e)
            except Exception:
                row[col] = None
        normalized_rows.append(row)

    return normalized_rows, include_columns


def _default_ris_columns() -> list[str]:
    """Canonical columns we create when ingesting RIS before criteria exists."""

    return [
        'Title',
        'Abstract',
        'Keywords',
        'Journal',
        'Year',
        'Authors',
        'DOI',
        'Type',
        'URL',
    ]


def _ris_value_for_canonical(col: str, entry: dict[str, Any]) -> Any:
    """Map canonical RIS columns to rispy normalized keys."""

    key = (col or '').strip().lower()
    if key == 'title':
        return entry.get('title') or entry.get('primary_title') or entry.get('short_title')
    if key == 'abstract':
        return entry.get('abstract') or entry.get('notes_abstract') or _join_list(entry.get('notes'), '\n')
    if key == 'keywords':
        return _join_list(entry.get('keywords'))
    if key == 'journal':
        return entry.get('secondary_title') or entry.get('journal_name')
    if key == 'year':
        return _extract_year(entry.get('year') or entry.get('publication_year') or entry.get('date'))
    if key == 'authors':
        return _join_list(entry.get('authors'))
    if key == 'doi':
        return entry.get('doi')
    if key == 'type':
        return entry.get('type_of_reference')
    if key == 'url':
        return _join_list(entry.get('urls'))

    # Fallback (shouldn't happen for our canonical list)
    v = entry.get(key)
    return _join_list(v) if isinstance(v, list) else v


def _parse_citations_ris_bytes_auto(raw_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse RIS into a canonical table shape.

    This is used when RIS is uploaded before SR criteria/config exists.
    """

    if not rispy:
        raise RuntimeError('RIS upload requested but rispy is not installed')

    try:
        text = raw_bytes.decode('utf-8-sig')
    except Exception:
        text = raw_bytes.decode('utf-8', errors='replace')

    entries = rispy.load(io.StringIO(text))
    cols = _default_ris_columns()
    if not entries:
        return [], cols

    rows: list[dict[str, Any]] = []
    for e in entries:
        row: dict[str, Any] = {}
        for c in cols:
            try:
                row[c] = _ris_value_for_canonical(c, e)
            except Exception:
                row[c] = None
        rows.append(row)

    return rows, cols


def _load_include_columns_from_criteria(sr_doc: dict[str, Any] | None = None) -> list[str]:
    # Delegate to consolidated postgres service
    try:
        return cits_dp_service.load_include_columns_from_criteria(sr_doc)
    except Exception:
        return []


def _parse_dsn(dsn: str) -> dict[str, str]:
    # Delegate to consolidated postgres service
    try:
        return parse_dsn(dsn)
    except Exception:
        return {}


def _create_table_and_insert_sync(table_name: str, columns: list[str], rows: list[dict[str, Any]]) -> int:
    return cits_dp_service.create_table_and_insert_sync(table_name, columns, rows)


def _extract_criteria_questions_from_sr(sr: dict[str, Any] | None) -> dict[str, str]:
    """Extract L1 criteria questions from SR criteria_parsed.

    Returns a dict mapping criterion_key -> question_text.
    Example: {"is_this_article_primary_research": "Is this article primary research?"}
    """
    if not sr:
        return {}

    criteria_parsed = sr.get('criteria_parsed') or {}
    l1_criteria = criteria_parsed.get('l1') or {}
    questions = l1_criteria.get('questions') or []

    result = {}
    for q in questions:
        if not isinstance(q, str) or not q.strip():
            continue
        # Use the same key generation as the screening system
        # snake_case already converts "Is this article primary research?" to "is_this_article_primary_research"
        criterion_key = snake_case(q, max_len=56)
        if not criterion_key:
            criterion_key = 'criterion'
        result[criterion_key] = q

    return result


def _match_csv_column_to_criterion(csv_col: str, criteria_questions: dict[str, str]) -> str | None:
    """Match a CSV column header to a criterion key.

    Handles the "L1 - " prefix and matches exactly against criteria questions.
    Returns the criterion_key if matched, None otherwise.
    """
    if not csv_col or not isinstance(csv_col, str):
        return None

    # Remove "L1 - " prefix if present
    col_text = csv_col.strip()
    if col_text.startswith('L1 - '):
        col_text = col_text[5:].strip()
    elif col_text.startswith('L2 - '):
        # Skip L2 columns for now
        return None

    # Match exactly against criteria questions
    for criterion_key, question_text in criteria_questions.items():
        if col_text == question_text:
            return criterion_key

    return None


def _configured_l1_answer_columns(sr: dict[str, Any] | None) -> dict[str, str]:
    """Return configured retrospective-answer headers mapped to L1 criterion keys."""
    if not sr:
        return {}
    criteria_parsed = sr.get('criteria_parsed') or {}
    l1_criteria = criteria_parsed.get('l1') or {}
    items = l1_criteria.get('items') or []
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        question = item.get('question')
        answer_column = item.get('answer_column')
        if not isinstance(question, str) or not question.strip():
            continue
        if not isinstance(answer_column, str) or not answer_column.strip():
            continue
        criterion_key = snake_case(question, max_len=56) or 'criterion'
        result[answer_column] = criterion_key
    return result


def _parse_human_answer_to_jsonb(answer_value: Any) -> dict[str, Any]:
    """Convert a CSV human answer value to JSONB format.

    Returns a dict with structure:
    {
        "selected": "Yes - primary research",
        "source": "csv_upload",
        "timestamp": "2025-03-18T...",
        "autofilled": true
    }
    """
    if answer_value is None or (isinstance(answer_value, str) and answer_value.strip() == ''):
        return {
            'selected': None,
            'source': 'csv_upload',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'autofilled': True,
        }

    selected_value = str(answer_value).strip() if answer_value else None

    return {
        'selected': selected_value,
        'source': 'csv_upload',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'autofilled': True,
    }


def _populate_human_answers_from_csv(
    table_name: str,
    normalized_rows: list[dict[str, Any]],
    include_columns: list[str],
    sr: dict[str, Any] | None,
) -> None:
    """Populate human_* JSONB columns from CSV data.

    This function:
    1. Extracts criteria questions from SR
    2. Matches CSV columns to criteria questions
    3. For each matched column, populates the corresponding human_l1_* column
    4. Backfills human decision columns
    """
    if not sr or not normalized_rows or not include_columns:
        return

    # Extract criteria questions
    criteria_questions = _extract_criteria_questions_from_sr(sr)
    if not criteria_questions:
        return

    # Build mapping of CSV column index to criterion_key. An explicit Answer
    # column selected during setup is authoritative for retrospective studies;
    # the legacy "L1 - <question>" convention remains supported as a fallback.
    configured_answer_columns = _configured_l1_answer_columns(sr)
    csv_col_to_criterion: dict[int, str] = {}
    for col_idx, col_name in enumerate(include_columns):
        criterion_key = resolve_source_value(
            configured_answer_columns, col_name,
        ) or _match_csv_column_to_criterion(col_name, criteria_questions)
        if criterion_key:
            csv_col_to_criterion[col_idx] = criterion_key

    if not csv_col_to_criterion:
        # No matching columns found
        return

    # Fetch all rows from the database to get actual citation IDs
    try:
        all_rows = cits_dp_service.get_citations_by_ids(
            list(range(1, len(normalized_rows) + 1)),
            table_name=table_name,
        )
    except Exception:
        # If we can't fetch rows, skip human answer population
        return

    # Build a map of row index to citation ID
    row_id_map: dict[int, int] = {}
    for idx, db_row in enumerate(all_rows):
        if db_row and 'id' in db_row:
            row_id_map[idx] = db_row['id']

    # Populate human answer columns for each row
    for row_idx, row in enumerate(normalized_rows):
        citation_id = row_id_map.get(row_idx)
        if not citation_id:
            continue

        for col_idx, criterion_key in csv_col_to_criterion.items():
            if col_idx >= len(include_columns):
                continue

            col_name = include_columns[col_idx]
            answer_value = row.get(col_name)

            # Convert to JSONB format
            human_jsonb = _parse_human_answer_to_jsonb(answer_value)

            # Uploaded retrospective answers are L1 source answers.
            human_col = f"human_l1_{criterion_key}"

            # Update the JSONB column
            try:
                cits_dp_service.update_jsonb_column(
                    citation_id=citation_id,
                    col=human_col,
                    data=human_jsonb,
                    table_name=table_name,
                )
            except Exception:
                # Best-effort; continue with other rows
                pass

    # Backfill human decision columns
    try:
        criteria_parsed = sr.get('criteria_parsed') or {}
        cits_dp_service.backfill_human_decisions(criteria_parsed, table_name)
    except Exception:
        # Best-effort; continue
        pass


async def _upload_screening_citations_impl(
    sr_id: str,
    file: UploadFile,
    current_user: dict[str, Any],
    *,
    force_format: str | None = None,
) -> UploadResult:
    """Shared implementation for citations upload (CSV or RIS)."""

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service, require_screening=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    # Check admin config
    if not _is_postgres_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Postgres not configured. Set POSTGRES_MODE and POSTGRES_* env vars.',
        )

    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='File is required',
        )

    # Read bytes once (UploadFile stream is not reliably seekable after read)
    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read upload: {e}",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Uploaded file is empty',
        )

    fmt = (force_format or _sniff_citations_format(file.filename, raw)).lower()
    if fmt not in ('csv', 'ris'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported citations format: {fmt}",
        )

    # Parse into normalized rows + include columns
    try:
        if fmt == 'csv':
            normalized_rows, include_columns = _parse_citations_csv_bytes(raw)
        else:
            # RIS is often uploaded before criteria config exists; derive columns directly from RIS.
            normalized_rows, include_columns = _parse_citations_ris_bytes_auto(
                raw,
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse {fmt.upper()}: {e}",
        )

    if len(include_columns) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No columns found to create screening table',
        )

    # Build a unique table name for this upload
    safe_sr = re.sub(r'[^0-9a-zA-Z_]', '_', sr_id)
    timestamp = int(time.time())
    table_name = f"sr_{safe_sr}_{timestamp}_cit"

    # If replacing, best-effort drop previous table (if any)
    try:
        old = (sr.get('screening_db') or {}).get('table_name')
        if old:
            await run_in_threadpool(cits_dp_service.drop_table, old)
    except Exception:
        pass

    # Create table and insert rows in threadpool
    try:
        inserted = await run_in_threadpool(_create_table_and_insert_sync, table_name, include_columns, normalized_rows)
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create table or insert rows: {e}",
        )

    # CSV values remain citation metadata. Human screening answers must come
    # from an explicit set-answer or human-classify action, never from import.

    # Save DB connection metadata into SR Mongo doc
    try:
        screening_info = {
            'screening_db': {
                'table_name': table_name,
                'created_at': datetime.utcnow().isoformat(),
                'rows': inserted,
            },
        }

        await run_in_threadpool(
            srdb_service.update_screening_db_info,
            sr_id,
            screening_info['screening_db'],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Table created ({table_name}) but failed to update Systematic Review entry: {e}",
        )

    return UploadResult(
        sr_id=sr_id,
        table_name=table_name,
        rows_inserted=inserted,
        message=f"Created screening table '{table_name}' and inserted {inserted} rows",
        created_at=datetime.utcnow().isoformat(),
    )


@router.post('/{sr_id}/upload-citations', response_model=UploadResult)
async def upload_screening_citations(
    sr_id: str,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Upload citations for screening.

    Accepts:
      - CSV (.csv)
      - RIS (.ris) or RIS as .txt

    The endpoint auto-detects format and ingests accordingly.

    Notes:
      - CSV uploads: table columns are taken from the CSV headers.
      - RIS uploads: table columns are derived from the RIS content (canonical fields).
    """

    return await _upload_screening_citations_impl(sr_id, file, current_user)


# Helper to list citation ids - delegated to core.postgres.list_citation_ids
# The blocking implementation lives in backend.api.core.postgres.list_citation_ids


@router.get('/{sr_id}/citations')
async def list_citation_ids(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user), filter_step: str | None = None,
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    if not screening:
        return {'citation_ids': []}

    table_name = (screening or {}).get('table_name') or 'citations'

    try:
        from ..services.screening_eligibility_service import screening_eligibility_service

        criteria = (sr or {}).get('criteria_parsed') or (
            sr or {}
        ).get('criteria') or {}
        stage = 'l1'
        if str(filter_step or '').strip().lower() == 'l1':
            stage = 'l2'
        elif str(filter_step or '').strip().lower() == 'l2':
            stage = 'extract'
        ids = await run_in_threadpool(
            screening_eligibility_service.list_eligible_ids,
            criteria=criteria,
            table_name=table_name,
            target_stage=stage,
        )
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        # If the SR points at a screening table that no longer exists (e.g. dropped),
        # treat it as "no citations" instead of poisoning the shared connection.
        if _is_undefined_table_error(e):
            return {'citation_ids': []}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB: {e}",
        )

    return {'citation_ids': ids}


@router.get('/{sr_id}/citations/batch')
async def get_citations_batch(
    sr_id: str,
    ids: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
    fields: str | None = None,
):
    """Get many citation rows for a given SR in a single request.

    IMPORTANT: This route MUST be registered before `/{citation_id}`.
    Otherwise FastAPI may match "batch" as the citation_id path param and
    raise a 422.

    Query params:
      - ids: comma-separated citation ids (required)
      - fields: optional comma-separated list of columns to return

    Returns:
      {"citations": [ { ..row.. }, ... ]}
    """

    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    table_name = (screening or {}).get('table_name') or 'citations'

    # Parse ids
    raw_ids = [p.strip() for p in (ids or '').split(',') if p.strip()]
    if not raw_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='ids is required',
        )
    parsed_ids: list[int] = []
    for p in raw_ids:
        try:
            parsed_ids.append(int(p))
        except Exception:
            continue
    if not parsed_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='ids must be a comma-separated list of integers',
        )

    parsed_fields: list[str] | None = None
    if fields is not None:
        f = [x.strip() for x in fields.split(',') if x.strip()]
        parsed_fields = f if f else []

    try:
        rows = await run_in_threadpool(
            cits_dp_service.get_citations_by_ids,
            parsed_ids,
            table_name,
            parsed_fields,
        )
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB: {e}",
        )

    return {'citations': rows}


@router.get('/{sr_id}/citations/workspace')
async def list_workspace_citations(
    sr_id: str,
    search: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
    columns: str | None = None,
    filters: str | None = None,
    duplicate_status: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Return all review-authorized References workspace citations."""
    try:
        _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to load systematic review or screening: {e}',
        )
    table_name = (screening or {}).get('table_name')
    if not table_name:
        return {'citations': [], 'total_count': 0, 'columns': ['id']}
    try:
        actor_id = current_user.get('email') or current_user.get('id')
        configured_fields = await run_in_threadpool(
            citation_deduplication_preferences_service.get_fields,
            sr_id, table_name, actor_id,
        )
        response = await run_in_threadpool(
            cits_dp_service.list_workspace_citations,
            table_name, search, sort, direction,
            [
                column.strip() for column in columns.split(
                    ',',
                ) if column.strip()
            ] if columns else None,
            json.loads(filters) if filters else None,
            configured_fields,
            duplicate_status,
            None,
            False,
        )
        cached = await run_in_threadpool(
            citation_duplicate_run_service.get_cached,
            sr_id, table_name, response.get('dataset_revision'),
            configured_fields or [
                column for column in response.get(
                    'columns', [],
                ) if column not in {'id', 'provenance'}
            ],
        )
        response = await run_in_threadpool(
            cits_dp_service.list_workspace_citations,
            table_name, search, sort, direction,
            [
                column.strip() for column in columns.split(
                    ',',
                ) if column.strip()
            ] if columns else None,
            json.loads(
                filters,
            ) if filters else None, configured_fields, duplicate_status,
            (cached or {}).get('result'), False,
        )
        reviews = await run_in_threadpool(
            citation_duplicate_review_service.list_reviews, sr_id, table_name,
        )
        reviews_by_group = {review['group_id']: review for review in reviews}
        for group in response.get('duplicate_groups', []):
            review = reviews_by_group.get(group.get('group_id'))
            if not review or review.get('decision') != 'confirmed_duplicate':
                continue
            member_ids = {
                int(value)
                for value in group.get('citation_ids', [])
                if value is not None
            }
            member_ids.update(
                int(member['id'])
                for member in group.get('members', [])
                if member.get('id') is not None
            )
            survivor_id = review.get('survivor_id')
            if survivor_id is None or int(survivor_id) not in member_ids:
                review['survivor_id'] = None
                review['stale'] = True
        resolved_group_ids = {
            group_id for group_id, review in reviews_by_group.items()
            if review.get('decision') == 'not_duplicate'
        }
        if resolved_group_ids:
            resolved_citation_ids = {
                int(citation_id)
                for group in response.get('duplicate_groups', [])
                if group.get('group_id') in resolved_group_ids
                for citation_id in group.get('citation_ids', [])
            }
            for citation in response.get('citations', []):
                if int(citation.get('id', 0)) in resolved_citation_ids:
                    citation['duplicate_status'] = 'no_match'
                    citation['duplicate_score'] = None
            for group in response.get('duplicate_groups', []):
                if group.get('group_id') in resolved_group_ids:
                    for member in group.get('members', []):
                        member['duplicate_status'] = 'no_match'
                        member['duplicate_score'] = None
            response['duplicate_counts'] = {
                status: sum(
                    1 for citation in response.get('citations', [])
                    if citation.get('duplicate_status') == status
                )
                for status in ('exact', 'possible', 'no_match')
            }
            if duplicate_status in {'exact', 'possible', 'no_match'}:
                response['citations'] = [
                    citation for citation in response.get('citations', [])
                    if citation.get('duplicate_status') == duplicate_status
                ]
                response['total_count'] = len(response['citations'])
        for group in response.get('duplicate_groups', []):
            group['review'] = reviews_by_group.get(group['group_id'])
        configured_fields = [
            column for column in (configured_fields or response.get('columns', []))
            if column not in {'id', 'provenance'}
        ]
        response['deduplication_fields'] = configured_fields
        response['duplicate_run'] = {
            'run_id': (cached or {}).get('run_id'),
            'status': 'succeeded' if cached else 'not_run',
        }
        return response
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        if _is_undefined_table_error(e):
            return {'citations': [], 'total_count': 0, 'columns': ['id']}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to query screening DB: {e}',
        )


@router.get('/{sr_id}/citations/workspace/preferences')
async def get_workspace_column_preferences(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        return {'columns': None}
    actor_id = current_user.get('email') or current_user.get('id')
    columns = await run_in_threadpool(
        citation_workspace_preferences_service.get_columns, sr_id, table_name, actor_id,
    )
    return {'columns': columns}


@router.delete('/{sr_id}/citations/workspace')
async def delete_workspace_citations(
    sr_id: str,
    payload: dict[str, Any],
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    citation_ids = [int(value) for value in payload.get('citation_ids', [])]
    if not table_name or not citation_ids:
        return {'deleted_count': 0}
    try:
        if payload.get('confirmed') is not True:
            raise HTTPException(
                status_code=400, detail='Deletion requires explicit confirmation',
            )
        query = payload.get('query') or {}
        actor_id = current_user.get('email') or current_user.get('id')
        configured_fields = await run_in_threadpool(
            citation_deduplication_preferences_service.get_fields,
            sr_id, table_name, actor_id,
        )
        current_workspace = await run_in_threadpool(
            cits_dp_service.list_workspace_citations,
            table_name,
            query.get('search'), query.get('sort'), query.get('direction'),
            query.get('columns'), query.get('filters'), configured_fields,
            query.get('duplicate_status'),
        )
        cached = await run_in_threadpool(
            citation_duplicate_run_service.get_cached,
            sr_id,
            table_name,
            current_workspace.get('dataset_revision'),
            configured_fields or [
                column
                for column in current_workspace.get('columns', [])
                if column not in {'id', 'provenance'}
            ],
        )
        current_workspace = await run_in_threadpool(
            cits_dp_service.list_workspace_citations,
            table_name,
            query.get('search'), query.get('sort'), query.get('direction'),
            query.get('columns'), query.get('filters'), configured_fields,
            query.get('duplicate_status'),
            (cached or {}).get('result'),
            False,
        )
        if payload.get('query_fingerprint') != current_workspace.get('query_fingerprint'):
            raise HTTPException(
                status_code=409, detail='The active query is stale',
            )
        active_ids = {
            int(row['id'])
            for row in current_workspace.get('citations', [])
        }
        if not set(citation_ids).issubset(active_ids):
            raise HTTPException(
                status_code=409, detail='Selection is outside the active query',
            )
        deletion = await run_in_threadpool(
            cits_dp_service.delete_citations,
            table_name,
            citation_ids,
            sr_id,
            current_workspace.get('dataset_revision'),
        )
        if cached and deletion.get('deleted_count'):
            updated_result = await run_in_threadpool(
                recompute_affected_duplicate_groups,
                cached.get('result') or {},
                set(citation_ids),
                configured_fields,
            )
            run_id = await run_in_threadpool(
                citation_duplicate_run_service.start,
                sr_id,
                table_name,
                deletion.get('dataset_revision'),
                configured_fields,
                actor_id,
            )
            await run_in_threadpool(
                citation_duplicate_run_service.finish,
                run_id,
                updated_result,
                None,
            )
            deletion['duplicate_run'] = {
                'run_id': run_id,
                'status': 'succeeded',
            }
        return deletion
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to delete citations: {exc}',
        )


class CitationDuplicateReviewRequest(BaseModel):
    group_id: str
    decision: str
    survivor_id: int | None = None


@router.get('/{sr_id}/citations/workspace/duplicate-reviews')
async def get_duplicate_reviews(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        return {'reviews': []}
    return {'reviews': await run_in_threadpool(citation_duplicate_review_service.list_reviews, sr_id, table_name)}


@router.put('/{sr_id}/citations/workspace/duplicate-reviews')
async def save_duplicate_review(
    sr_id: str,
    payload: CitationDuplicateReviewRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        raise HTTPException(
            status_code=400, detail='Citation dataset is not configured',
        )
    actor_id = current_user.get('email') or current_user.get('id') or 'unknown'
    try:
        configured_fields = await run_in_threadpool(
            citation_deduplication_preferences_service.get_fields,
            sr_id, table_name, actor_id,
        )
        current_workspace = await run_in_threadpool(
            cits_dp_service.list_workspace_citations,
            table_name, None, None, None, None, None, configured_fields, None,
        )
        cached = await run_in_threadpool(
            citation_duplicate_run_service.get_cached,
            sr_id,
            table_name,
            current_workspace.get('dataset_revision'),
            configured_fields or [
                column
                for column in current_workspace.get('columns', [])
                if column not in {'id', 'provenance'}
            ],
        )
        if cached:
            current_workspace = await run_in_threadpool(
                cits_dp_service.list_workspace_citations,
                table_name,
                None,
                None,
                None,
                None,
                None,
                configured_fields,
                None,
                cached.get('result'),
                False,
            )
        group = next(
            (
                item for item in current_workspace.get('duplicate_groups', [])
                if item.get('group_id') == payload.group_id
            ),
            None,
        )
        if not group:
            raise HTTPException(
                status_code=409, detail='Duplicate group is stale',
            )
        member_ids = {
            int(value)
            for value in group.get('citation_ids', [])
            if value is not None
        }
        member_ids.update(
            int(member['id'])
            for member in group.get('members', [])
            if member.get('id') is not None
        )
        survivor_id = (
            int(payload.survivor_id) if payload.survivor_id is not None else None
        )
        if payload.decision == 'confirmed_duplicate' and survivor_id not in member_ids:
            raise HTTPException(
                status_code=400, detail='Survivor must belong to the duplicate group',
            )
        review = await run_in_threadpool(
            citation_duplicate_review_service.save_review,
            sr_id, table_name, payload.group_id, payload.decision,
            survivor_id, actor_id,
        )
        return review
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put('/{sr_id}/citations/workspace/preferences')
async def save_workspace_column_preferences(
    sr_id: str,
    payload: CitationWorkspaceColumnsRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Citation dataset is not configured',
        )

    actor_id = current_user.get('email') or current_user.get('id')
    try:
        columns = await run_in_threadpool(
            citation_workspace_preferences_service.save_columns,
            sr_id, table_name, actor_id, payload.columns,
        )
        return {'columns': columns}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )


class CitationDeduplicationFieldsRequest(BaseModel):
    fields: list[str]


@router.get('/{sr_id}/citations/workspace/deduplication-preferences')
async def get_workspace_deduplication_preferences(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        return {'fields': None}
    actor_id = current_user.get('email') or current_user.get('id')
    fields = await run_in_threadpool(
        citation_deduplication_preferences_service.get_fields,
        sr_id, table_name, actor_id,
    )
    return {'fields': fields}


@router.post('/{sr_id}/citations/workspace/duplicate-runs')
async def run_workspace_deduplication(
    sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        raise HTTPException(
            status_code=400, detail='Citation dataset is not configured',
        )
    actor_id = current_user.get('email') or current_user.get('id') or 'unknown'
    configured = await run_in_threadpool(
        citation_deduplication_preferences_service.get_fields, sr_id, table_name, actor_id,
    )
    configured = configured or [
        item['column_name'] for item in await run_in_threadpool(cits_dp_service.get_table_columns, table_name)
        if item['column_name'] not in {'id', 'provenance'}
    ]
    cached = await run_in_threadpool(
        citation_duplicate_run_service.get_cached, sr_id, table_name, (), configured,
    )
    try:
        revision, result = await run_in_threadpool(cits_dp_service.load_duplicate_rows, table_name, configured)
        run_id = await run_in_threadpool(
            citation_duplicate_run_service.start, sr_id, table_name, revision, configured, actor_id,
        )
        await run_in_threadpool(citation_duplicate_run_service.finish, run_id, result, None)
        return {'run_id': run_id, 'status': 'succeeded', 'dataset_revision': revision, 'fields': configured}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f'Duplicate calculation failed: {exc}',
        )


@router.put('/{sr_id}/citations/workspace/deduplication-preferences')
async def save_workspace_deduplication_preferences(
    sr_id: str,
    payload: CitationDeduplicationFieldsRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name')
    if not table_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Citation dataset is not configured',
        )
    actor_id = current_user.get('email') or current_user.get('id')
    available = [
        item['column_name']
        for item in cits_dp_service.get_table_columns(table_name)
    ]
    try:
        fields = await run_in_threadpool(
            citation_deduplication_preferences_service.save_fields,
            sr_id, table_name, actor_id, payload.fields, available,
        )
        return {'fields': fields}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )


# Helper to get citation row by id - delegated to backend.api.core.postgres.get_citation_by_id


@router.get('/{sr_id}/citations/{citation_id}')
async def get_citation_by_id(
    sr_id: str,
    citation_id: int,
    current_user: dict[str, Any] = Depends(get_current_active_user),
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    table_name = (screening or {}).get('table_name') or 'citations'

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB: {e}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail='Citation not found',
        )

    return row


# API model + helper to build a combined citation string from selected columns
class CombinedRequest(BaseModel):
    include_columns: list[str] | None = None


def _build_combined_citation_from_row(row: dict[str, Any], include_columns: list[str]) -> str:
    # Delegate to consolidated postgres service
    return cits_dp_service.build_combined_citation_from_row(row, include_columns)


@router.post('/{sr_id}/citations/{citation_id}/combined')
async def build_combined_citation(
    sr_id: str,
    citation_id: int,
    payload: CombinedRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    if not screening:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='No screening database configured for this systematic review',
        )

    table_name = (screening or {}).get('table_name') or 'citations'

    try:
        row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB: {e}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail='Citation not found',
        )

    # As a final fallback, use all columns present in include columns
    data = []
    for k in row.keys():
        if k not in payload.include_columns:
            continue
        # Convert snake_case DB name back to a more human header (replace _ with space and title-case)
        data.append(k)

    combined = _build_combined_citation_from_row(row, data)
    return {'sr_id': sr_id, 'citation_id': citation_id, 'combined_citation': combined}


# Helper to update citation fulltext - delegated to backend.api.core.postgres.update_citation_fulltext


@router.post('/{sr_id}/citations/{citation_id}/upload-fulltext')
async def upload_citation_fulltext(
    sr_id: str,
    citation_id: int,
    file: UploadFile = File(...),
    mode: str = 'replace',
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    mode = str(mode or '').strip().lower()
    if mode not in {'replace', 'supplementary'}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mode must be 'replace' or 'supplementary'",
        )
    # The backend is authoritative: a PDF-linkage worker and manual upload must
    # never compete for an SR. A final conditional worker update remains the
    # race-safe fallback for uploads that began just before job creation.
    try:
        from ..jobs.run_all_repo import run_all_repo
        await run_in_threadpool(run_all_repo.ensure_tables)
        active_job = await run_in_threadpool(run_all_repo.get_active_job_for_sr, sr_id)
        if active_job and active_job.get('pipeline_key') == 'pdf_linkage':
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    'message': 'PDF linkage is active; cancel or wait before uploading',
                    'job_id': active_job.get('job_id'),
                    'pipeline_key': active_job.get('pipeline_key'),
                    'status': active_job.get('status'),
                },
            )
    except HTTPException:
        raise
    except Exception:
        # Do not turn a scheduler availability problem into loss of the existing
        # manual-upload fallback.
        pass
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review or screening: {e}",
        )

    # Validate file
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='File is required',
        )

    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    # Prefer PDFs but allow other types if necessary; restrict to .pdf here
    if ext != '.pdf':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only PDF files are accepted for full text upload',
        )

    content = await file.read()
    # Verify citation exists BEFORE uploading blob to storage
    table_name = (screening or {}).get('table_name') or 'citations'

    try:
        existing_row = await run_in_threadpool(cits_dp_service.get_citation_by_id, int(citation_id), table_name)
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB: {e}",
        )

    if not existing_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail='Citation not found',
        )

    try:
        from ..services.fulltext_attachment_service import (
            add_supplementary_document, attach_fulltext_document,
        )
        if mode == 'supplementary':
            result = await add_supplementary_document(
                citation_id=citation_id, table_name=table_name,
                user_id=str(current_user['id']), filename=file.filename, content=content,
            )
        else:
            result = await attach_fulltext_document(
                citation_id=citation_id,
                table_name=table_name,
                user_id=str(current_user['id']),
                filename=file.filename,
                content=content,
                source='manual',
                replace=True,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to attach full text: {e}",
        )
    if not result.attached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Citation not found to attach fulltext file',
        )
    return {
        'status': 'success',
        'sr_id': sr_id,
        'citation_id': citation_id,
        'storage_path': result.storage_path,
        'document_id': result.document_id,
    }


@router.get('/{sr_id}/citations/{citation_id}/fulltext-documents')
async def get_fulltext_documents(
    sr_id: str, citation_id: int,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name') or 'citations'
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        raise HTTPException(status_code=404, detail='Citation not found')
    from ..services.fulltext_attachment_service import ensure_legacy_document, list_fulltext_documents
    await run_in_threadpool(ensure_legacy_document, citation_id, table_name, row)
    documents = await run_in_threadpool(list_fulltext_documents, citation_id, table_name)
    return {'documents': documents, 'title': row.get('title') or row.get('citation') or ''}


@router.get('/{sr_id}/citations/{citation_id}/fulltext-documents/{document_id}/download')
async def download_fulltext_document(
    sr_id: str, citation_id: int, document_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Download a citation attachment after checking SR membership and linkage."""
    _, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name') or 'citations'
    row = await run_in_threadpool(cits_dp_service.get_citation_by_id, citation_id, table_name)
    if not row:
        raise HTTPException(status_code=404, detail='Citation not found')
    from ..services.fulltext_attachment_service import ensure_legacy_document, get_fulltext_document
    from ..services.storage import storage_service
    await run_in_threadpool(ensure_legacy_document, citation_id, table_name, row)
    document = await run_in_threadpool(
        get_fulltext_document, citation_id, table_name, document_id,
    )
    if not document:
        raise HTTPException(
            status_code=404, detail='Full-text document not found',
        )
    try:
        content, filename = await storage_service.get_bytes_by_path(document['storage_path'])
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail='Full-text file not found in storage',
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail='Invalid full-text storage path',
        ) from exc
    return StreamingResponse(
        iter([content]), media_type='application/pdf',
        headers={
            'Content-Disposition': f'inline; filename="{filename or document["filename"]}"',
            'Cache-Control': 'no-store, max-age=0',
        },
    )


class ActivateDocumentRequest(BaseModel):
    document_id: str


@router.post('/{sr_id}/citations/{citation_id}/fulltext-documents/activate')
async def activate_document(
    sr_id: str, citation_id: int, payload: ActivateDocumentRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name') or 'citations'
    from ..services.fulltext_attachment_service import activate_fulltext_document
    activated = await run_in_threadpool(
        activate_fulltext_document, citation_id, table_name, payload.document_id,
    )
    if not activated:
        raise HTTPException(
            status_code=404, detail='Full-text document not found',
        )
    return {'status': 'success'}


@router.delete('/{sr_id}/citations/{citation_id}/fulltext-documents/{document_id}')
async def delete_document(
    sr_id: str, citation_id: int, document_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    _, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    table_name = (screening or {}).get('table_name') or 'citations'
    from ..services.fulltext_attachment_service import delete_fulltext_document
    deleted, was_active = await delete_fulltext_document(citation_id, table_name, document_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail='Full-text document not found',
        )
    return {'status': 'success', 'was_active': was_active}


# Helper to list fulltext URLs - delegated to backend.api.core.postgres.list_fulltext_urls


# Helper to drop a database - delegated to backend.api.core.postgres.drop_database
async def hard_delete_screening_resources(sr_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load systematic review: {e}",
        )

    requester_id = current_user.get('email')
    try:
        srdb_service.require_review_owner(sr_id, requester_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Only the owner may perform screening cleanup for this systematic review',
        ) from exc

    if not screening:
        return {'status': 'no_screening_db', 'message': 'No screening table configured for this SR', 'deleted_table': False, 'deleted_files': 0}

    table_name = screening.get('table_name')
    if not table_name:
        return {'status': 'no_screening_db', 'message': 'Incomplete screening DB metadata', 'deleted_table': False, 'deleted_files': 0}

    # 1) collect fulltext URLs from the screening DB
    try:
        urls = await run_in_threadpool(cits_dp_service.list_fulltext_urls, table_name)
        from ..services.fulltext_attachment_service import list_registered_storage_paths
        registered_urls = await run_in_threadpool(list_registered_storage_paths, table_name)
        urls = list(dict.fromkeys([*(urls or []), *(registered_urls or [])]))
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query screening DB for fulltext URLs: {e}",
        )

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
            if '/' in u:
                container, blob = u.split('/', 1)
            else:
                # unrecognised format, skip
                failed_files += 1
                continue

            # prefer to use storage_service.delete_user_document when we can parse user/doc/filename
            parsed_ok = False
            if storage_service:
                try:
                    # blob expected: users/{user_id}/documents/{doc_id}_{filename}
                    if blob.startswith('users/'):
                        parts = blob.split('/')
                        # expect ["users", user_id, "documents", "{doc_id}_{filename}"]
                        if len(parts) >= 4 and parts[2] == 'documents':
                            user_id = parts[1]
                            # handle any extra slashes in filename
                            doc_part = '/'.join(parts[3:])
                            # split first underscore to get doc_id and filename
                            if '_' in doc_part:
                                doc_id, filename = doc_part.split('_', 1)
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
        try:
            from ..services.fulltext_attachment_service import delete_document_registry
            await run_in_threadpool(delete_document_registry, table_name)
        except Exception:
            # The citation table is authoritative; stale registry rows are harmless
            # and can be reconciled separately if registry cleanup is unavailable.
            pass
        table_dropped = True
    except RuntimeError as rexc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(rexc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to drop screening table: {e}",
        )

    # 4) remove screening_db metadata from SR document
    try:
        await run_in_threadpool(
            srdb_service.clear_screening_db_info,
            sr_id,
        )
    except Exception:
        # non-fatal, but report it
        pass

    return {
        'status': 'success',
        'sr_id': sr_id,
        'deleted_table': table_dropped,
        'deleted_files': deleted_files,
        'failed_file_deletions': failed_files,
    }


# Optional endpoint to trigger the cleanup directly
@router.post('/{sr_id}/hard-clean')
async def hard_clean_screening_endpoint(sr_id: str, current_user: dict[str, Any] = Depends(get_current_active_user)):
    result = await hard_delete_screening_resources(sr_id, current_user)
    return result


def _safe_export_filename(sr: dict[str, Any], sr_id: str) -> str:
    raw = str((sr or {}).get('name') or (sr or {}).get('title') or sr_id)
    safe = re.sub(r'[^A-Za-z0-9_-]+', '_', raw).strip('_')[:80] or 'review'
    return f'sr_{safe}_citations_{datetime.utcnow().date().isoformat()}.csv'


async def _load_export_context(sr_id: str, current_user: dict[str, Any]):
    try:
        sr, screening = await load_sr_and_check(sr_id, current_user, srdb_service)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to load systematic review: {exc}',
        )
    if not screening:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='No screening database configured for this systematic review',
        )
    return sr, (screening or {}).get('table_name') or 'citations'


@router.get('/{sr_id}/export-schema', response_model=CitationExportSchema)
async def get_citation_export_schema(
    sr_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Return only current, safe semantic fields available for this SR."""
    sr, table_name = await _load_export_context(sr_id, current_user)
    try:
        return await run_in_threadpool(citation_export_service.build_schema, sr, table_name)
    except ExportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )


@router.post('/{sr_id}/export-citations')
async def export_citations_selective(
    sr_id: str,
    payload: CitationExportRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Generate a CSV exclusively from server-resolved semantic selections."""
    sr, table_name = await _load_export_context(sr_id, current_user)
    try:
        csv_bytes = await run_in_threadpool(
            citation_export_service.export_csv, table_name, sr, payload,
        )
    except ExportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        )
    return Response(
        content=csv_bytes,
        media_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename="{_safe_export_filename(sr, sr_id)}"',
        },
    )
