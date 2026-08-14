"""Authoritative screening-stage decision and eligibility rules.

Answer JSONB columns are the source of truth. The ``human_l*_decision``
columns are derived caches used for efficient filtering and are repaired before
they are used to determine eligibility for a later screening stage.
"""
from __future__ import annotations

import json
from typing import Any

from .cit_db_service import cits_dp_service
from .cit_db_service import snake_case


def _answer_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith('{'):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def selected_answer(row: dict[str, Any], question: str, stage: str) -> str | None:
    """Return the human answer, falling back to the stage's LLM answer.

    The critical agent is advisory: disagreements are routed to human review
    but do not change the main screening agent's progression decision.
    """
    core = snake_case(question, max_len=56)
    if not core:
        return None
    columns = (
        f'human_{stage}_{core}',
        f'llm_{stage}_{core}',
        f'llm_{core}',
    )
    for column in columns:
        selected = _answer_object(row.get(column)).get('selected')
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
    return None


def compute_stage_decision(
    row: dict[str, Any], questions: list[str], stage: str,
) -> str:
    """Compute include/exclude for one stage from current criterion answers.

    Missing criteria produce ``undecided``. A missing answer is conservatively
    excluded, matching the established CAN-SR progression behavior.
    """
    valid_questions = [
        q for q in questions if isinstance(q, str) and q.strip()
    ]
    if not valid_questions:
        return 'undecided'
    for question in valid_questions:
        selected = selected_answer(row, question, stage)
        if selected is None or 'exclude' in selected.lower():
            return 'exclude'
    return 'include'


def compute_screening_decisions(
    row: dict[str, Any], criteria: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return the derived L1 and cumulative L2 decisions for a citation."""
    criteria = criteria if isinstance(criteria, dict) else {}
    l1 = criteria.get('l1') if isinstance(criteria.get('l1'), dict) else {}
    l2 = criteria.get('l2') if isinstance(criteria.get('l2'), dict) else {}
    l1_questions = l1.get('questions') if isinstance(
        l1.get('questions'), list,
    ) else []
    l2_questions = l2.get('questions') if isinstance(
        l2.get('questions'), list,
    ) else []
    l1_decision = compute_stage_decision(row, l1_questions, 'l1')
    l2_decision = 'undecided'
    if l1_questions or l2_questions:
        l2_decision = 'include'
        for question, question_stage in [
            *((q, 'l1') for q in l1_questions),
            *((q, 'l2') for q in l2_questions),
        ]:
            selected = selected_answer(row, question, question_stage)
            if selected is None:
                l2_decision = 'exclude'
                break
            if 'exclude' in selected.lower():
                l2_decision = 'exclude'
                break
    return l1_decision, l2_decision


class ScreeningEligibilityService:
    """Resolve stage scope only after repairing derived decision caches."""

    def __init__(self, repository: Any = None) -> None:
        self.repository = repository or cits_dp_service

    def list_eligible_ids(
        self,
        *,
        criteria: dict[str, Any] | None,
        table_name: str,
        target_stage: str,
        repair_decisions: bool = True,
    ) -> list[int]:
        """Return citation IDs eligible for ``target_stage``.

        Progression callers should keep ``repair_decisions=True`` so derived
        decision caches are refreshed before they are used. Read-only reporting
        callers can set it to ``False`` to avoid turning concurrent metrics
        requests into repeated, table-wide writes.
        """
        stage = str(target_stage or '').strip().lower()
        if stage not in {'l1', 'l2', 'extract'}:
            raise ValueError(f'Unsupported screening stage: {target_stage!r}')

        if stage == 'l1':
            return self.repository.list_citation_ids(None, table_name)

        # Later stages depend on derived decisions. Progression paths repair
        # first and fail loudly; reporting paths only read the existing cache.
        if repair_decisions:
            self.repository.backfill_human_decisions(
                criteria or {}, table_name,
            )
        source_stage = 'l1' if stage == 'l2' else 'l2'
        return self.repository.list_citation_ids(source_stage, table_name)


screening_eligibility_service = ScreeningEligibilityService()
