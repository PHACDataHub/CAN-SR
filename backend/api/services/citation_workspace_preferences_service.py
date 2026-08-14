"""Persistence for non-sensitive, per-user citation workspace presentation state."""
from __future__ import annotations

import json
import re

from .postgres_auth import postgres_server

_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class CitationWorkspacePreferencesService:
    def _validate_table_name(self, table_name: str) -> str:
        if not _IDENTIFIER.fullmatch(table_name or ''):
            raise ValueError('Invalid citation table name')
        return table_name

    def get_columns(self, sr_id: str, table_name: str, user_id: str) -> list[str] | None:
        table_name = self._validate_table_name(table_name)
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''SELECT columns FROM citation_workspace_column_preferences
                   WHERE sr_id = %s AND citation_table_name = %s AND user_id = %s''',
                (sr_id, table_name, user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            columns = row[0]
            if isinstance(columns, str):
                columns = json.loads(columns)
            return [column for column in columns if isinstance(column, str)] if isinstance(columns, list) else None
        finally:
            cur.close()

    def save_columns(self, sr_id: str, table_name: str, user_id: str, columns: list[str]) -> list[str]:
        table_name = self._validate_table_name(table_name)
        if not columns or any(not isinstance(column, str) for column in columns):
            raise ValueError('At least one visible column is required')
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_workspace_column_preferences
                   (sr_id, citation_table_name, user_id, columns)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (sr_id, citation_table_name, user_id) DO UPDATE
                   SET columns = EXCLUDED.columns, updated_at = CURRENT_TIMESTAMP''',
                (sr_id, table_name, user_id, json.dumps(columns)),
            )
            conn.commit()
            return columns
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_workspace_preferences_service = CitationWorkspacePreferencesService()
