"""Failure-safe full-text staging and atomic citation attachment."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi.concurrency import run_in_threadpool

from .cit_db_service import cits_dp_service
from .postgres_auth import postgres_server
from .storage import storage_service

MAX_PDF_BYTES = int(os.getenv('PDF_LINKAGE_MAX_BYTES', str(50 * 1024 * 1024)))


@dataclass(frozen=True)
class AttachmentResult:
    attached: bool
    reason: str
    storage_path: str | None = None
    document_id: str | None = None


def _ensure_document_table() -> None:
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS citation_fulltext_documents (
            table_name TEXT NOT NULL,
            citation_id BIGINT NOT NULL,
            document_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            file_md5 TEXT NOT NULL,
            document_type TEXT NOT NULL DEFAULT 'supplementary',
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            extracted_text TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (table_name, citation_id, document_id)
        )""",
    )
    conn.commit()


def list_fulltext_documents(citation_id: int, table_name: str) -> list[dict]:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """SELECT document_id, filename, storage_path, file_md5, document_type,
                  is_active, extracted_text IS NOT NULL, created_at
             FROM citation_fulltext_documents
            WHERE table_name=%s AND citation_id=%s
            ORDER BY is_active DESC, created_at""",
        (table_name, int(citation_id)),
    )
    return [
        {
            'document_id': row[0], 'filename': row[1], 'storage_path': row[2],
            'file_md5': row[3], 'document_type': row[4], 'is_active': bool(row[5]),
            'is_extracted': bool(row[6]), 'created_at': row[7].isoformat() if row[7] else None,
        }
        for row in (cur.fetchall() or [])
    ]


def ensure_legacy_document(citation_id: int, table_name: str, row: dict) -> None:
    """Backfill the registry for PDFs attached before multi-document support."""
    path = str(row.get('fulltext_url') or '')
    file_md5 = str(row.get('fulltext_md5') or '')
    if not path:
        return
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        'SELECT 1 FROM citation_fulltext_documents WHERE table_name=%s AND citation_id=%s AND storage_path=%s',
        (table_name, int(citation_id), path),
    )
    if cur.fetchone():
        return
    tail = path.rsplit('/', 1)[-1]
    document_id, _, filename = tail.partition('_')
    _register_document(
        citation_id, table_name, document_id or f'legacy-{citation_id}',
        filename or tail or f'fulltext_{citation_id}.pdf', path,
        file_md5 or 'unknown', 'main', True,
    )


def _register_document(
    citation_id: int, table_name: str, document_id: str, filename: str,
    storage_path: str, file_md5: str, document_type: str, is_active: bool,
) -> None:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    if is_active:
        cur.execute(
            'UPDATE citation_fulltext_documents SET is_active=FALSE WHERE table_name=%s AND citation_id=%s',
            (table_name, int(citation_id)),
        )
    cur.execute(
        """INSERT INTO citation_fulltext_documents
             (table_name, citation_id, document_id, filename, storage_path, file_md5, document_type, is_active)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (table_name, citation_id, document_id) DO UPDATE SET
               filename=EXCLUDED.filename, storage_path=EXCLUDED.storage_path,
               file_md5=EXCLUDED.file_md5, document_type=EXCLUDED.document_type,
               is_active=EXCLUDED.is_active""",
        (
            table_name, int(citation_id), document_id, filename,
            storage_path, file_md5, document_type, is_active,
        ),
    )
    conn.commit()


async def add_supplementary_document(
    *, citation_id: int, table_name: str, user_id: str, filename: str, content: bytes,
) -> AttachmentResult:
    file_md5 = validate_pdf(content)
    safe_name = os.path.basename(
        filename,
    ) or f'supplementary_{citation_id}.pdf'
    document_id = await storage_service.upload_user_document(
        user_id=user_id, filename=safe_name, file_content=content,
    )
    if not document_id:
        raise RuntimeError('storage_upload_failed')
    path = f'{storage_service.container_name}/users/{user_id}/documents/{document_id}_{safe_name}'
    try:
        await run_in_threadpool(
            _register_document, citation_id, table_name, str(
                document_id,
            ), safe_name,
            path, file_md5, 'supplementary', False,
        )
    except Exception:
        await _delete_path(path)
        raise
    return AttachmentResult(True, 'linked', path, str(document_id))


def activate_fulltext_document(citation_id: int, table_name: str, document_id: str) -> bool:
    _ensure_document_table()
    conn = postgres_server.conn
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT storage_path, file_md5 FROM citation_fulltext_documents
                WHERE table_name=%s AND citation_id=%s AND document_id=%s FOR UPDATE""",
            (table_name, int(citation_id), document_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return False
        cur.execute(
            'UPDATE citation_fulltext_documents SET is_active=FALSE WHERE table_name=%s AND citation_id=%s',
            (table_name, int(citation_id)),
        )
        cur.execute(
            'UPDATE citation_fulltext_documents SET is_active=TRUE WHERE table_name=%s AND citation_id=%s AND document_id=%s',
            (table_name, int(citation_id), document_id),
        )
        # The legacy columns remain the compatibility contract for viewer/extraction.
        cur.execute(
            f'''UPDATE "{table_name}" SET fulltext_url=%s, fulltext_md5=%s,
                fulltext=NULL, fulltext_coords=NULL, fulltext_pages=NULL,
                fulltext_figures=NULL, fulltext_tables=NULL WHERE id=%s''',
            (row[0], row[1], int(citation_id)),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def record_active_extracted_text(citation_id: int, table_name: str, text: str) -> None:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """UPDATE citation_fulltext_documents SET extracted_text=%s
            WHERE table_name=%s AND citation_id=%s AND is_active=TRUE""",
        (text, table_name, int(citation_id)),
    )
    conn.commit()


_NUMBERED_SENTENCE_RE = re.compile(
    r'(?m)^\s*\[(\d+)\]\s*(.*?)(?=\n\s*\[\d+\]\s|\Z)', re.DOTALL,
)


def format_combined_fulltext(rows: list[tuple[str, str, str]], fallback: str) -> str:
    """Build document boundaries and globally unique evidence sentence indices."""
    if not rows:
        return fallback
    next_index = 0
    documents: list[str] = []
    for name, kind, text in rows:
        sentences = [
            match.group(2).strip()
            for match in _NUMBERED_SENTENCE_RE.finditer(text or '')
        ]
        if sentences:
            numbered = []
            for sentence in sentences:
                numbered.append(f'[{next_index}] {sentence}')
                next_index += 1
            body = '\n\n'.join(numbered)
        else:
            body = str(text or '').strip()
        documents.append(f'=== DOCUMENT: {name} ({kind}) ===\n{body}')
    return '\n\n'.join(documents)


def get_fulltext_document(citation_id: int, table_name: str, document_id: str) -> dict[str, Any] | None:
    """Resolve a document only inside an already-authorized citation scope."""
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """SELECT document_id, filename, storage_path, file_md5, document_type,
                  is_active, extracted_text IS NOT NULL
             FROM citation_fulltext_documents
            WHERE table_name=%s AND citation_id=%s AND document_id=%s""",
        (table_name, int(citation_id), document_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        'document_id': row[0], 'filename': row[1], 'storage_path': row[2],
        'file_md5': row[3], 'document_type': row[4], 'is_active': bool(row[5]),
        'is_extracted': bool(row[6]),
    }


def list_registered_storage_paths(table_name: str) -> list[str]:
    """List all attachment blobs for review cleanup, including supplements."""
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        'SELECT DISTINCT storage_path FROM citation_fulltext_documents WHERE table_name=%s',
        (table_name,),
    )
    return [str(row[0]) for row in (cur.fetchall() or []) if row and row[0]]


def delete_document_registry(table_name: str) -> int:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        'DELETE FROM citation_fulltext_documents WHERE table_name=%s', (
            table_name,
        ),
    )
    deleted = cur.rowcount or 0
    conn.commit()
    return deleted


def combined_fulltext(citation_id: int, table_name: str, fallback: str) -> str:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """SELECT filename, document_type, extracted_text
             FROM citation_fulltext_documents
            WHERE table_name=%s AND citation_id=%s AND extracted_text IS NOT NULL
            ORDER BY is_active DESC, created_at""",
        (table_name, int(citation_id)),
    )
    rows = cur.fetchall() or []
    return format_combined_fulltext(rows, fallback)


async def delete_fulltext_document(citation_id: int, table_name: str, document_id: str) -> tuple[bool, bool]:
    _ensure_document_table()
    conn = postgres_server.conn
    cur = conn.cursor()
    cur.execute(
        """SELECT storage_path, is_active FROM citation_fulltext_documents
            WHERE table_name=%s AND citation_id=%s AND document_id=%s""",
        (table_name, int(citation_id), document_id),
    )
    row = cur.fetchone()
    if not row:
        return False, False
    path, was_active = str(row[0]), bool(row[1])
    cur.execute(
        'DELETE FROM citation_fulltext_documents WHERE table_name=%s AND citation_id=%s AND document_id=%s',
        (table_name, int(citation_id), document_id),
    )
    if was_active:
        cur.execute(
            f'''UPDATE "{table_name}" SET fulltext_url=NULL, fulltext_md5=NULL,
                fulltext=NULL, fulltext_coords=NULL, fulltext_pages=NULL,
                fulltext_figures=NULL, fulltext_tables=NULL WHERE id=%s''',
            (int(citation_id),),
        )
    conn.commit()
    await _delete_path(path)
    return True, was_active


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
        cur.execute(
            'DELETE FROM fulltext_blob_cleanup WHERE storage_path=%s', (path,),
        )
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
    await run_in_threadpool(
        _register_document, citation_id, table_name, str(
            document_id,
        ), safe_name,
        path, file_md5, 'main', True,
    )
    old_url = result.get('old_url')
    if old_url and old_url != path:
        def forget_replaced() -> None:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                'DELETE FROM citation_fulltext_documents WHERE table_name=%s AND citation_id=%s AND storage_path=%s',
                (table_name, int(citation_id), str(old_url)),
            )
            conn.commit()
        await run_in_threadpool(forget_replaced)
        await _delete_path(str(old_url))
    return AttachmentResult(True, 'linked', path, str(document_id))
