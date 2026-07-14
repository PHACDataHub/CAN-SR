"""Failure-safe full-text staging and atomic citation attachment."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from fastapi.concurrency import run_in_threadpool

from .cit_db_service import cits_dp_service
from .storage import storage_service
from .postgres_auth import postgres_server

MAX_PDF_BYTES = int(os.getenv('PDF_LINKAGE_MAX_BYTES', str(50 * 1024 * 1024)))


@dataclass(frozen=True)
class AttachmentResult:
    attached: bool
    reason: str
    storage_path: str | None = None
    document_id: str | None = None


def validate_pdf(content: bytes) -> str:
    if not content or len(content) > MAX_PDF_BYTES:
        raise ValueError('invalid_pdf_size')
    if not content.lstrip().startswith(b'%PDF'):
        raise ValueError('invalid_pdf')
    return hashlib.md5(content).hexdigest()


def _record_cleanup(path: str, error: str) -> None:
    """Persist failed blob deletion so transient storage errors do not leak forever."""
    conn = postgres_server.conn
    try:
        cur = conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS fulltext_blob_cleanup (
                storage_path TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_attempt_at TIMESTAMPTZ
            )""",
        )
        cur.execute(
            """INSERT INTO fulltext_blob_cleanup (storage_path, attempts, last_error, last_attempt_at)
               VALUES (%s, 1, %s, now())
               ON CONFLICT (storage_path) DO UPDATE SET
                 attempts=fulltext_blob_cleanup.attempts + 1,
                 last_error=EXCLUDED.last_error, last_attempt_at=now()""",
            (path, str(error)[:2000]),
        )
        conn.commit()
    except Exception:
        conn.rollback()


async def _delete_path(path: str | None, *, persist_failure: bool = True) -> bool:
    if not path:
        return False
    pattern = rf'^{re.escape(storage_service.container_name)}/users/([^/]+)/documents/([^_]+)_(.+)$'
    match = re.match(pattern, path)
    if match:
        try:
            await storage_service.delete_user_document(*match.groups())
            return True
        except Exception as exc:
            if persist_failure:
                await run_in_threadpool(_record_cleanup, path, str(exc))
            return False
    return False


async def reconcile_pending_blob_cleanup(limit: int = 50) -> int:
    """Retry durable cleanup records; return the number successfully removed."""
    def pending() -> list[str]:
        conn = postgres_server.conn
        cur = conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS fulltext_blob_cleanup (
                storage_path TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_attempt_at TIMESTAMPTZ)""",
        )
        cur.execute(
            'SELECT storage_path FROM fulltext_blob_cleanup ORDER BY created_at LIMIT %s',
            (max(1, int(limit)),),
        )
        rows = [str(row[0]) for row in (cur.fetchall() or [])]
        conn.commit()
        return rows

    def forget(path: str) -> None:
        conn = postgres_server.conn
        cur = conn.cursor()
        cur.execute('DELETE FROM fulltext_blob_cleanup WHERE storage_path=%s', (path,))
        conn.commit()

    removed = 0
    for path in await run_in_threadpool(pending):
        if await _delete_path(path, persist_failure=False):
            await run_in_threadpool(forget, path)
            removed += 1
        else:
            await run_in_threadpool(_record_cleanup, path, 'cleanup_retry_failed')
    return removed


async def attach_fulltext_document(
    *,
    citation_id: int,
    table_name: str,
    user_id: str,
    filename: str,
    content: bytes,
    source: str,
    source_url: str | None = None,
    replace: bool = False,
) -> AttachmentResult:
    """Stage a PDF, atomically attach it, and clean up losing blobs."""
    file_md5 = validate_pdf(content)
    safe_name = os.path.basename(filename) or f'fulltext_{citation_id}.pdf'
    document_id = await storage_service.upload_user_document(
        user_id=user_id, filename=safe_name, file_content=content,
    )
    if not document_id:
        raise RuntimeError('storage_upload_failed')
    path = (
        f'{storage_service.container_name}/users/{user_id}/documents/'
        f'{document_id}_{safe_name}'
    )
    try:
        result = await run_in_threadpool(
            cits_dp_service.attach_fulltext_atomic,
            citation_id,
            path,
            file_md5,
            source=source,
            source_url=source_url,
            replace=replace,
            table_name=table_name,
        )
    except Exception:
        await _delete_path(path)
        raise
    if not result.get('attached'):
        await _delete_path(path)
        return AttachmentResult(False, str(result.get('reason') or 'not_attached'))
    old_url = result.get('old_url')
    if old_url and old_url != path:
        await _delete_path(str(old_url))
    return AttachmentResult(True, 'linked', path, str(document_id))