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
                    '''SELECT fields, threshold FROM citation_deduplication_preferences
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

    def get_threshold(self, sr_id: str, table_name: str, user_id: str) -> float:
        if not _IDENTIFIER.fullmatch(table_name or ''):
            raise ValueError('Invalid citation table name')
        cur = postgres_server.conn.cursor()
        try:
            try:
                cur.execute(
                    '''SELECT threshold FROM citation_deduplication_preferences
                       WHERE sr_id=%s AND citation_table_name=%s AND user_id=%s''',
                    (sr_id, table_name, user_id),
                )
            except Exception:
                postgres_server.conn.rollback()
                return 0.70
            row = cur.fetchone()
            value = row[0] if row else 0.70
            return float(value) if float(value) in {0.5, 0.7, 0.8} else 0.70
        finally:
            cur.close()

    def save_threshold(self, sr_id: str, table_name: str, user_id: str, threshold: float) -> float:
        threshold = float(threshold)
        if threshold not in {0.5, 0.7, 0.8}:
            raise ValueError('Threshold must be 0.5, 0.7, or 0.8')
        fields = self.get_fields(sr_id, table_name, user_id) or []
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_deduplication_preferences
                   (sr_id,citation_table_name,user_id,fields,threshold)
                   VALUES (%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT (sr_id,citation_table_name,user_id) DO UPDATE
                   SET threshold=EXCLUDED.threshold, updated_at=CURRENT_TIMESTAMP''',
                (sr_id, table_name, user_id, json.dumps(fields), threshold),
            )
            conn.commit()
            return threshold
        except Exception:
            conn.rollback()
            raise
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
        merged = list(dict.fromkeys(requested))
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_deduplication_preferences
                   (sr_id,citation_table_name,user_id,fields,threshold)
                   VALUES (%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT (sr_id,citation_table_name,user_id) DO UPDATE
                   SET fields=EXCLUDED.fields, updated_at=CURRENT_TIMESTAMP''',
                (
                    sr_id, table_name, user_id, json.dumps(merged),
                    self.get_threshold(sr_id, table_name, user_id),
                ),
            )
            conn.commit()
            return merged
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_deduplication_preferences_service = CitationDeduplicationPreferencesService()
