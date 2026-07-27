"""Core multi-reviewer domain services.

This module is deliberately independent of the assignment UI. It provides
stable work-unit identity, authenticated reviewer identity normalization, the
canonical validation repository boundary, and legacy projection helpers. The
existing screening/extraction routers can adopt these operations incrementally
without moving their current response contracts.
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Protocol


class ReviewConnection(Protocol):
    def cursor(self): ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class WorkUnit:
    sr_id: str
    stage: str
    source_table_name: str
    citation_id: int
    criteria_revision: int
    criterion_key: str | None = None
    parameter_key: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in {'l1', 'l2', 'extract'}:
            raise ValueError(f'Unsupported review stage: {self.stage}')
        if self.citation_id < 0:
            raise ValueError('citation_id must be non-negative')
        if self.parameter_key and not self.criterion_key:
            raise ValueError('parameter_key requires criterion_key')
        if not self.source_table_name or not re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_]*', self.source_table_name,
        ):
            raise ValueError('source_table_name is not a safe SQL identifier')

    def values(self) -> tuple[Any, ...]:
        return (
            self.sr_id, self.stage, self.source_table_name, self.citation_id,
            self.criterion_key, self.parameter_key, self.criteria_revision,
        )


@dataclass(frozen=True)
class ReviewerIdentity:
    reviewer_id: str
    email: str | None = None


def reviewer_identity(current_user: dict[str, Any]) -> ReviewerIdentity:
    """Derive a stable identity from the authenticated user, never a payload."""
    raw_id = current_user.get('id') or current_user.get(
        'user_id',
    ) or current_user.get('sub')
    email = current_user.get('email')
    if not raw_id and not email:
        raise ValueError('Authenticated user has no stable reviewer identity')
    normalized_email = str(email).strip().casefold() if email else None
    # Legacy tokens may only contain an email. Keep this deterministic until a
    # membership service supplies a permanent user ID.
    return ReviewerIdentity(str(raw_id or normalized_email), normalized_email)


def normalize_extraction_answer(value: Any) -> str:
    """Normalize presentation-only differences for agreement checks."""
    text = unicodedata.normalize('NFKC', '' if value is None else str(value))
    text = re.sub(r'<[^>]*>', '', text)
    return ' '.join(text.casefold().split())


def extraction_answers_agree(left: Any, right: Any) -> bool:
    return normalize_extraction_answer(left) == normalize_extraction_answer(right)


class ReviewRepository:
    """Persistence boundary for canonical review records.

    SQL is kept here so routers remain responsible for HTTP/authentication and
    the legacy projector remains independently testable.
    """

    def __init__(self, connection: ReviewConnection):
        self.connection = connection

    @staticmethod
    def _work_unit_where(unit: WorkUnit) -> tuple[str, tuple[Any, ...]]:
        return (
            '''sr_id = %s AND stage = %s AND source_table_name = %s
               AND citation_id = %s AND criteria_revision = %s
               AND criterion_key IS NOT DISTINCT FROM %s
               AND parameter_key IS NOT DISTINCT FROM %s''',
            (
                unit.sr_id, unit.stage, unit.source_table_name, unit.citation_id,
                unit.criteria_revision, unit.criterion_key, unit.parameter_key,
            ),
        )

    def save_draft(
        self,
        unit: WorkUnit,
        reviewer: ReviewerIdentity,
        answer: Any,
        *,
        explanation: str | None = None,
        evidence: Any = None,
        assignment_id: str | None = None,
        client_request_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._save(
            unit, reviewer, answer, 'draft', explanation, evidence,
            assignment_id, client_request_id, expected_version,
        )

    def validate(
        self,
        unit: WorkUnit,
        reviewer: ReviewerIdentity,
        answer: Any,
        *,
        explanation: str | None = None,
        evidence: Any = None,
        assignment_id: str | None = None,
        client_request_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._save(
            unit, reviewer, answer, 'validated', explanation, evidence,
            assignment_id, client_request_id, expected_version,
        )

    def visible_validations(
        self, unit: WorkUnit, reviewer: ReviewerIdentity,
    ) -> list[dict[str, Any]]:
        """Return only records the current reviewer is allowed to see.

        Drafts are private. Other reviewers' validated answers become visible
        only after the current reviewer has locked their own validation.
        """
        conn = self.connection
        cur = conn.cursor()
        try:
            where, params = self._work_unit_where(unit)
            cur.execute(
                f'''SELECT id, reviewer_id, state, revision, answer_json,
                           explanation, evidence_json, created_at, validated_at, version
                    FROM review_validations
                    WHERE {where} AND state IN ('draft', 'validated')
                    ORDER BY reviewer_id, revision''',
                params,
            )
            rows = cur.fetchall()
            own_validated = any(
                row[1] == reviewer.reviewer_id and row[2] == 'validated'
                for row in rows
            )
            visible = [
                row for row in rows
                if row[1] == reviewer.reviewer_id
                or (own_validated and row[2] == 'validated')
            ]
            return [
                {
                    'id': row[0], 'reviewer_id': row[1], 'state': row[2],
                    'revision': row[3], 'answer': row[4],
                    'explanation': row[5], 'evidence': row[6],
                    'created_at': row[7], 'validated_at': row[8],
                    'version': row[9],
                }
                for row in visible
            ]
        finally:
            cur.close()

    def remove_current(self, unit: WorkUnit, reviewer: ReviewerIdentity) -> int:
        """Remove the current draft/validated record for a reviewer."""
        cur = self.connection.cursor()
        try:
            where, params = self._work_unit_where(unit)
            cur.execute(
                f'''DELETE FROM review_validations
                    WHERE {where} AND reviewer_id = %s
                      AND state IN ('draft', 'validated')''',
                (*params, reviewer.reviewer_id),
            )
            deleted = cur.rowcount
            self.connection.commit()
            return deleted
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cur.close()

    def _save(
        self, unit: WorkUnit, reviewer: ReviewerIdentity, answer: Any,
        state: str, explanation: str | None, evidence: Any,
        assignment_id: str | None, client_request_id: str | None,
        expected_version: int | None,
    ) -> dict[str, Any]:
        if state not in {'draft', 'validated'}:
            raise ValueError(f'Unsupported write state: {state}')
        conn = self.connection
        cur = conn.cursor()
        row_id = str(uuid.uuid4())
        try:
            where, params = self._work_unit_where(unit)
            if client_request_id:
                cur.execute(
                    '''SELECT id, reviewer_id, state, revision, version
                       FROM review_validations
                       WHERE reviewer_id = %s AND client_request_id = %s''',
                    (reviewer.reviewer_id, client_request_id),
                )
                request_row = cur.fetchone()
                if request_row:
                    # Retrying a request returns the original result and does
                    # not create another revision or overwrite another user.
                    conn.rollback()
                    return {
                        'id': request_row[0], 'reviewer_id': request_row[1],
                        'state': request_row[2], 'revision': request_row[3],
                        'version': request_row[4], 'idempotent_replay': True,
                    }
            cur.execute(
                f'''SELECT id, version, state FROM review_validations
                    WHERE {where} AND reviewer_id = %s
                      AND state IN ('draft', 'validated')
                    ORDER BY revision DESC LIMIT 1 FOR UPDATE''',
                (*params, reviewer.reviewer_id),
            )
            current = cur.fetchone()
            if current and expected_version is not None and current[1] != expected_version:
                raise RuntimeError('review validation version conflict')
            revision = 1
            if current:
                cur.execute(
                    'SELECT COALESCE(MAX(revision), 0) + 1 FROM review_validations '
                    f'WHERE {where} AND reviewer_id = %s',
                    (*params, reviewer.reviewer_id),
                )
                revision = int(cur.fetchone()[0])
                cur.execute(
                    "UPDATE review_validations SET state = 'superseded', version = version + 1 "
                    'WHERE id = %s', (current[0],),
                )
            now = datetime.now(timezone.utc)
            cur.execute(
                '''INSERT INTO review_validations
                   (id, assignment_id, sr_id, stage, source_table_name, citation_id,
                    criterion_key, parameter_key, criteria_revision, reviewer_id,
                    revision, state, answer_json, explanation, evidence_json, source,
                    client_request_id, created_at, validated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s::jsonb, %s, %s::jsonb, 'user', %s, %s, %s)''',
                (
                    row_id, assignment_id, unit.sr_id, unit.stage,
                    unit.source_table_name, unit.citation_id, unit.criterion_key,
                    unit.parameter_key, unit.criteria_revision, reviewer.reviewer_id,
                    revision, state, json.dumps(answer), explanation,
                    json.dumps(evidence) if evidence is not None else None,
                    client_request_id, now, now if state == 'validated' else None,
                ),
            )
            conn.commit()
            return {
                'id': row_id, 'reviewer_id': reviewer.reviewer_id,
                'state': state, 'revision': revision, 'version': 1,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


class CompatibilityProjector:
    """Pure mapping helpers for legacy response/column projections."""

    @staticmethod
    def validation_entry(record: dict[str, Any]) -> dict[str, str]:
        reviewer = record.get('reviewer_id') or record.get('email') or ''
        validated_at = record.get(
            'validated_at',
        ) or record.get('created_at') or ''
        return {'user': str(reviewer), 'validated_at': str(validated_at)}

    @staticmethod
    def legacy_validation_list(records: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            CompatibilityProjector.validation_entry(record)
            for record in records if record.get('state') == 'validated'
        ]
