"""Runtime helpers for applying canonical criteria to stored citation values."""
from __future__ import annotations

from typing import Any

from ..services.cit_db_service import snake_case_column


def _selected(row: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Return the latest human/LLM selected label for a criteria item."""
    slug = snake_case_column(
        str(item.get('question') or item.get('name') or ''),
    )
    prefixes = ('human_param_', 'llm_param_') if item.get(
        'name',
    ) else ('human_', 'llm_')
    for prefix in prefixes:
        value = row.get(f'{prefix}{slug}')
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ('selected', 'value'):
                if isinstance(value.get(key), str):
                    return value[key]
    return None


def item_is_visible(criteria: dict[str, Any], item: dict[str, Any], row: dict[str, Any]) -> bool:
    """Evaluate an item's AND trigger conditions against a citation row.

    Missing source answers fail closed: a dependent item must not be screened or
    extracted before its prerequisite has a matching answer.
    """
    items = [
        *(criteria.get('l1') or []), *(
            criteria.get('l2')
            or []
        ), *(criteria.get('parameters') or []),
    ]
    by_id = {str(candidate.get('id')): candidate for candidate in items if isinstance(candidate, dict)}
    for condition in ((item.get('trigger') or {}).get('all') or []):
        source = by_id.get(str(condition.get('source_item_id')))
        if not source:
            return False
        selected = _selected(row, source)
        option = next(
            (
                answer for answer in [*(source.get('answers') or []), *(source.get('options') or [])]
                if str(answer.get('id')) == str(condition.get('option_id'))
            ), None,
        )
        if not option or selected != option.get('label'):
            return False
    return True
