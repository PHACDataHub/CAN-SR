"""Runtime helpers for applying canonical criteria to stored citation values."""
from __future__ import annotations

from typing import Any

from ..services.cit_db_service import snake_case


def _value(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ('selected', 'value'):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def selected_value(
    row: dict[str, Any], item: dict[str, Any], stage: str,
) -> str | None:
    """Return human answer first, then the unconditionally usable LLM answer."""
    slug = snake_case(
        str(item.get('question') or item.get('name') or ''), max_len=56,
    )
    if not slug:
        return None
    human_prefix = 'human_param_' if stage == 'parameters' else f'human_{stage}_'
    llm_prefix = 'llm_param_' if stage == 'parameters' else f'llm_{stage}_'
    # Generic llm_* is retained as a compatibility read for legacy rows.
    for column in (
        f'{human_prefix}{slug}',
        f'{llm_prefix}{slug}',
        f'llm_{slug}' if stage in {'l1', 'l2'} else None,
    ):
        if column:
            answer = _value(row.get(column))
            if answer is not None:
                return answer
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
    by_id = {
        str(candidate.get('id')): candidate for candidate in items if isinstance(candidate, dict)
    }
    for condition in ((item.get('trigger') or {}).get('all') or []):
        source = by_id.get(str(condition.get('source_item_id')))
        if not source:
            return False
        if any(source is candidate for candidate in (criteria.get('parameters') or [])):
            source_stage = 'parameters'
        elif any(source is candidate for candidate in (criteria.get('l2') or [])):
            source_stage = 'l2'
        else:
            source_stage = 'l1'
        selected = selected_value(row, source, source_stage)
        option = next(
            (
                answer for answer in [*(source.get('answers') or []), *(source.get('options') or [])]
                if str(answer.get('id')) == str(condition.get('option_id'))
            ), None,
        )
        if not option or selected != option.get('label'):
            return False
    return True
