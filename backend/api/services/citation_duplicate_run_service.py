"""Persistence for explicit, dataset-scoped duplicate calculations."""
from __future__ import annotations

import json
import uuid
from datetime import date
from datetime import datetime
from typing import Any

from .postgres_auth import postgres_server


def _json_default(value: Any) -> str:
    """Serialize database date/time values in duplicate-run JSON results."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(
        f'Object of type {type(value).__name__} is not JSON serializable',
    )


class CitationDuplicateRunService:
    def _key(self, revision: Any, fields: list[str]) -> tuple[str, str]:
        return json.dumps(revision, sort_keys=True, default=str), json.dumps(fields, separators=(',', ':'))

    def get_cached(self, sr_id: str, table_name: str, revision: Any, fields: list[str]) -> dict[str, Any] | None:
        revision_json, fields_json = self._key(revision, fields)
        cur = postgres_server.conn.cursor()
        try:
            try:
                cur.execute(
                    '''SELECT id, status, result, error, started_at, completed_at
                       FROM citation_duplicate_runs
                       WHERE sr_id=%s AND citation_table_name=%s
                         AND dataset_revision=%s::jsonb AND fields=%s::jsonb
                         AND status='succeeded'
                       ORDER BY completed_at DESC LIMIT 1''',
                    (sr_id, table_name, revision_json, fields_json),
                )
            except Exception:
                postgres_server.conn.rollback()
                return None
            row = cur.fetchone()
            if not row:
                return None
            result = row[2] if not isinstance(row, dict) else row.get('result')
            return {
                'run_id': str(row[0] if not isinstance(row, dict) else row.get('id')),
                'status': row[1] if not isinstance(row, dict) else row.get('status'),
                'result': json.loads(result) if isinstance(result, str) else result,
                'error': row[3] if not isinstance(row, dict) else row.get('error'),
            }
        finally:
            cur.close()

    def start(self, sr_id: str, table_name: str, revision: Any, fields: list[str], actor: str) -> str:
        run_id = str(uuid.uuid4())
        revision_json, fields_json = self._key(revision, fields)
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_duplicate_runs
                   (id,sr_id,citation_table_name,dataset_revision,fields,status,requested_by)
                   VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,'running',%s)''',
                (run_id, sr_id, table_name, revision_json, fields_json, actor),
            )
            conn.commit()
            return run_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def finish(self, run_id: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''UPDATE citation_duplicate_runs
                   SET status=%s, result=%s::jsonb, error=%s, completed_at=CURRENT_TIMESTAMP
                   WHERE id=%s''',
                (
                    'succeeded' if result is not None else 'failed',
                    json.dumps(
                        result, default=_json_default,
                    ) if result is not None else None,
                    error,
                    run_id,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_duplicate_run_service = CitationDuplicateRunService()
