"""Per-user, per-review deduplication field configuration."""
from __future__ import annotations

import json

from .citation_workspace_preferences_service import _IDENTIFIER
from .postgres_auth import postgres_server


class CitationDeduplicationPreferencesService:
    def get_fields(self, sr_id: str, table_name: str, user_id: str) -> list[str] | None:
        if not _IDENTIFIER.fullmatch(table_name or ''):
            raise ValueError('Invalid citation table name')
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            try:
                cur.execute(
                    '''SELECT fields FROM citation_deduplication_preferences
                       WHERE sr_id=%s AND citation_table_name=%s AND user_id=%s''',
                    (sr_id, table_name, user_id),
                )
            except Exception:
                conn.rollback()
                return None
            row = cur.fetchone()
            if not row:
                return None
            fields = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return [field for field in fields if isinstance(field, str)] if isinstance(fields, list) else None
        finally:
            cur.close()

    def save_fields(
        self,
        sr_id: str,
        table_name: str,
        user_id: str,
        fields: list[str],
        available: list[str],
    ) -> list[str]:
        allowed = set(available)
        requested = [
            field for field in fields
            if field in allowed and field not in {'id', 'provenance'}
        ]
        existing = [
            field for field in (self.get_fields(sr_id, table_name, user_id) or [])
            if field != 'provenance'
        ]
        merged = list(dict.fromkeys(existing + requested))
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_deduplication_preferences
                   (sr_id,citation_table_name,user_id,fields)
                   VALUES (%s,%s,%s,%s::jsonb)
                   ON CONFLICT (sr_id,citation_table_name,user_id) DO UPDATE
                   SET fields=EXCLUDED.fields, updated_at=CURRENT_TIMESTAMP''',
                (sr_id, table_name, user_id, json.dumps(merged)),
            )
            conn.commit()
            return merged
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_deduplication_preferences_service = CitationDeduplicationPreferencesService()
