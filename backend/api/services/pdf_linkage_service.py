"""Conservative Open Access Button lookup, bounded PDF download, and attachment."""
from __future__ import annotations

import ipaddress
import asyncio
import os
import random
import socket
import logging
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

from .cit_db_service import cits_dp_service
from .fulltext_attachment_service import attach_fulltext_document
from .pubmed_doi_service import resolve_doi_from_pubmed

MAX_BYTES = int(os.getenv('PDF_LINKAGE_MAX_BYTES', str(50 * 1024 * 1024)))
OA_API_BASE_URL = os.getenv(
    'OA_API_BASE_URL', 'https://api.openaccessbutton.org/availability',
).rstrip('/')
OA_CONTACT = os.getenv('OA_API_CONTACT', 'CAN-SR')
MAX_RETRIES = max(0, int(os.getenv('PDF_LINKAGE_MAX_RETRIES', '3')))
MAX_CONCURRENCY = max(1, int(os.getenv('PDF_LINKAGE_MAX_CONCURRENCY', '4')))
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_DOWNLOAD_LIMIT = asyncio.Semaphore(MAX_CONCURRENCY)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfLinkOutcome:
    kind: str
    status: str
    reason: str | None = None


def normalize_doi(value: object) -> str:
    doi = str(value or '').strip()
    lowered = doi.lower()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'doi:'):
        if lowered.startswith(prefix):
            return doi[len(prefix):].strip()
    return doi


def _is_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return False
    try:
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        return all(
            ipaddress.ip_address(item[4][0]).is_global
            for item in socket.getaddrinfo(parsed.hostname, port)
        )
    except (OSError, ValueError):
        return False


def _candidate(payload: object) -> str | None:
    if isinstance(payload, list):
        return next((url for item in payload if (url := _candidate(item))), None)
    if isinstance(payload, dict):
        for key in ('url_for_pdf', 'pdf_url', 'download_url', 'url'):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(('https://', 'http://')):
                return value
        for key in ('data', 'results', 'availability', 'best_oa_location', 'oa_locations'):
            if url := _candidate(payload.get(key)):
                return url
    return None


async def _download(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    current = url
    for _ in range(6):
        if not _is_public_url(current):
            raise ValueError('unsafe_pdf_url')
        async with client.stream('GET', current, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('location')
                if not location:
                    raise ValueError('invalid_redirect')
                current = str(response.url.join(location))
                continue
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').lower()
            if content_type and not any(
                item in content_type for item in ('pdf', 'octet-stream')
            ):
                raise ValueError('invalid_pdf_content_type')
            content = bytearray()
            async for part in response.aiter_bytes():
                content.extend(part)
                if len(content) > MAX_BYTES:
                    raise ValueError('pdf_too_large')
            data = bytes(content)
            if not data.lstrip().startswith(b'%PDF'):
                raise ValueError('invalid_pdf')
            return data, str(response.url)
    raise ValueError('too_many_redirects')


async def _request_with_retry(
    client: httpx.AsyncClient, url: str,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.get(url, follow_redirects=False)
            if response.status_code not in RETRYABLE_STATUSES:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f'retryable status {response.status_code}',
                request=response.request,
                response=response,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
        if attempt < MAX_RETRIES:
            await asyncio.sleep(min(4.0, 0.25 * (2 ** attempt)) + random.random() * 0.1)
    assert last_error is not None
    raise last_error


async def link_citation_pdf(*, citation_id: int, table_name: str, user_id: str) -> PdfLinkOutcome:
    row = cits_dp_service.get_citation_by_id(citation_id, table_name)
    if not row:
        return PdfLinkOutcome('failed', 'failed', 'citation_not_found')
    if row.get('fulltext_url'):
        cits_dp_service.update_pdf_linkage_outcome(
            citation_id, status='skipped_existing_fulltext',
            reason='concurrent_fulltext', table_name=table_name,
        )
        return PdfLinkOutcome('skipped', 'skipped_existing_fulltext', 'concurrent_fulltext')
    doi = normalize_doi(row.get('doi'))
    if not doi:
        doi = normalize_doi(await resolve_doi_from_pubmed(row))
    if doi:
        # This conditional update is race-safe and leaves an existing DOI intact.
        if not normalize_doi(row.get('doi')):
            saved = cits_dp_service.save_recovered_doi(
                citation_id, doi, source='pubmed', table_name=table_name,
            )
            if not saved:
                # A DOI written concurrently takes precedence over discovery.
                current = cits_dp_service.get_citation_by_id(citation_id, table_name)
                doi = normalize_doi((current or {}).get('doi')) or doi
    else:
        cits_dp_service.update_pdf_linkage_outcome(
            citation_id, status='manual_upload_required', reason='missing_doi',
            table_name=table_name,
        )
        return PdfLinkOutcome('skipped', 'manual_upload_required', 'missing_doi')

    try:
        async with _DOWNLOAD_LIMIT:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, connect=10),
                headers={'User-Agent': f'CAN-SR PDF linkage ({OA_CONTACT})'},
            ) as client:
                response = await _request_with_retry(
                    client, f'{OA_API_BASE_URL}?doi={quote(doi, safe="")}',
                )
                candidate = _candidate(response.json())
                if not candidate:
                    raise LookupError('oa_not_found')
                pdf, final_url = await _download(client, candidate)

        attachment = await attach_fulltext_document(
            citation_id=citation_id,
            table_name=table_name,
            user_id=user_id,
            filename=f'oa_{citation_id}.pdf',
            content=pdf,
            source='oaapi',
            source_url=final_url,
        )
        if not attachment.attached:
            logger.info('pdf_linkage outcome=concurrent_fulltext citation_id=%s', citation_id)
            return PdfLinkOutcome('skipped', 'skipped_existing_fulltext', 'concurrent_fulltext')
        logger.info('pdf_linkage outcome=linked citation_id=%s', citation_id)
        return PdfLinkOutcome('done', 'linked')
    except LookupError:
        reason = 'oa_not_found'
    except (httpx.HTTPError, ValueError) as exc:
        reason = str(exc) if str(exc) in {
            'unsafe_pdf_url', 'invalid_pdf', 'invalid_pdf_content_type',
            'pdf_too_large', 'too_many_redirects', 'invalid_redirect',
        } else 'download_unavailable'
    except Exception as exc:
        cits_dp_service.update_pdf_linkage_outcome(
            citation_id, status='failed', reason='technical_failure',
            error=str(exc), table_name=table_name,
        )
        return PdfLinkOutcome('failed', 'failed', 'technical_failure')

    cits_dp_service.update_pdf_linkage_outcome(
        citation_id, status='manual_upload_required', reason=reason,
        table_name=table_name,
    )
    logger.info('pdf_linkage outcome=manual_upload_required reason=%s citation_id=%s', reason, citation_id)
    return PdfLinkOutcome('skipped', 'manual_upload_required', reason)