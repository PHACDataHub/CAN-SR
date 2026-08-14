"""Persistence and safety checks for human duplicate review decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .citation_import_schema import is_protected_citation_column
from .citation_workspace_preferences_service import _IDENTIFIER
from .postgres_auth import postgres_server

DECISIONS = {'confirmed_duplicate', 'not_duplicate', 'deferred'}
METADATA_FIELDS = (
    'title', 'abstract', 'authors', 'author',
    'journal', 'year', 'publication_year', 'keywords', 'url',
)
IDENTIFIER_FIELDS = ('doi', 'pmid', 'pmcid', 'url', 'fulltext_url')


def suggest_survivor(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose a stable survivor using completeness, identifiers, age, then ID."""
    def rank(member: dict[str, Any]) -> tuple[int, int, float, int]:
        completeness = sum(
            bool(member.get(field))
            for field in METADATA_FIELDS
        )
        identifiers = sum(
            (len(IDENTIFIER_FIELDS) - index) * bool(member.get(field))
            for index, field in enumerate(IDENTIFIER_FIELDS)
        )
        created = member.get('created_at') or member.get('imported_at')
        try:
            age = -created.timestamp() if hasattr(created, 'timestamp') else - \
                datetime.fromisoformat(str(created)).timestamp()
        except (TypeError, ValueError, OverflowError):
            age = 0.0
        try:
            citation_id = int(member.get('id', 0))
        except (TypeError, ValueError):
            citation_id = 0
        return completeness, identifiers, age, -citation_id

    if not members:
        return {'suggested_survivor_id': None, 'survivor_reason': None}
    winner = max(members, key=rank)
    winner_rank = rank(winner)
    reasons = (
        'most_complete_metadata', 'strongest_identifier',
        'oldest_record', 'lowest_id',
    )
    reason = reasons[-1]
    for index, candidate in enumerate(reasons):
        if sum(rank(member)[index] == winner_rank[index] for member in members) == 1:
            reason = candidate
            break
    return {'suggested_survivor_id': winner.get('id'), 'survivor_reason': reason}


class CitationDuplicateReviewService:
    def list_reviews(self, sr_id: str, table_name: str) -> list[dict[str, Any]]:
        self._validate(table_name)
        cur = postgres_server.conn.cursor()
        try:
            try:
                cur.execute(
                    '''SELECT group_id, decision, survivor_id, updated_by, updated_at
                       FROM citation_duplicate_reviews
                       WHERE sr_id=%s AND citation_table_name=%s
                       ORDER BY group_id''', (sr_id, table_name),
                )
            except Exception:
                postgres_server.conn.rollback()
                return []
            rows = cur.fetchall() or []
            return [self._row(row) for row in rows]
        finally:
            cur.close()

    def save_review(
        self, sr_id: str, table_name: str, group_id: str, decision: str,
        survivor_id: int | None, actor_id: str,
    ) -> dict[str, Any]:
        self._validate(table_name)
        if decision not in DECISIONS:
            raise ValueError('Invalid duplicate review decision')
        if decision == 'confirmed_duplicate' and survivor_id is None:
            raise ValueError('A survivor is required for confirmed duplicates')
        if decision != 'confirmed_duplicate':
            survivor_id = None
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(
                '''INSERT INTO citation_duplicate_reviews
                   (sr_id,citation_table_name,group_id,decision,survivor_id,updated_by)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (sr_id,citation_table_name,group_id) DO UPDATE
                   SET decision=EXCLUDED.decision, survivor_id=EXCLUDED.survivor_id,
                       updated_by=EXCLUDED.updated_by, updated_at=CURRENT_TIMESTAMP''',
                (sr_id, table_name, group_id, decision, survivor_id, actor_id),
            )
            conn.commit()
            return {
                'group_id': group_id, 'decision': decision,
                'survivor_id': survivor_id, 'updated_by': actor_id,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def protected_ids(self, table_name: str, citation_ids: list[int]) -> list[int]:
        self._validate(table_name)
        ids = sorted({int(value) for value in citation_ids})
        if not ids:
            return []
        cur = postgres_server.conn.cursor()
        try:
            cur.execute(
                '''SELECT column_name FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s''', (table_name,),
            )
            columns = [
                row[0] if not isinstance(
                    row, dict,
                ) else row['column_name'] for row in cur.fetchall() or []
            ]
            protected = [
                column for column in columns if is_protected_citation_column(column) or column in {
                    'screening_decision', 'l1_decision', 'l2_decision',
                }
            ]
            if not protected:
                return []
            placeholders = ','.join(['%s'] * len(ids))
            checks = ' OR '.join(
                f'NULLIF(CAST("{column}" AS TEXT), \'\') IS NOT NULL' for column in protected
            )
            cur.execute(
                f'SELECT id FROM "{table_name}" WHERE id IN ({placeholders}) AND ({checks})',
                tuple(ids),
            )
            return [int(row[0] if not isinstance(row, dict) else row['id']) for row in cur.fetchall() or []]
        finally:
            cur.close()

    @staticmethod
    def _validate(table_name: str) -> None:
        if not _IDENTIFIER.fullmatch(table_name or ''):
            raise ValueError('Invalid citation table name')

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return dict(row)
        return {
            'group_id': row[0], 'decision': row[1], 'survivor_id': row[2],
            'updated_by': row[3], 'updated_at': row[4],
        }


citation_duplicate_review_service = CitationDuplicateReviewService()
