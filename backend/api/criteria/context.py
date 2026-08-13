"""Canonical citation and imported-answer context helpers.

This module deliberately has no database or web dependencies so prompt builders,
CSV/RIS importers, and tests all use the same matching and formatting rules.
"""
from __future__ import annotations

import re
from typing import Any


def resolve_source_value(row: dict[str, Any], header: str | None) -> Any:
    """Resolve a configured source header without silently guessing."""
    if not header:
        return None
    if header in row:
        return row[header]
    normalized = _normalize_key(header)
    matches = [
        value for key, value in row.items(
        ) if _normalize_key(str(key)) == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.strip().casefold()).strip('_')


def normalize_answer_text(value: Any) -> str:
    """Normalize formatting only; semantic synonyms are intentionally excluded."""
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def match_answer_label(raw_value: Any, options: list[dict[str, Any]]) -> dict[str, Any]:
    """Match a raw value to an option label and retain the raw audit value."""
    raw = '' if raw_value is None else str(raw_value)
    if not raw.strip():
        return {'status': 'blank', 'raw': raw, 'label': None, 'option_id': None}
    normalized = normalize_answer_text(raw)
    for option in options:
        label = str(option.get('label') or '')
        if normalized == normalize_answer_text(label):
            return {'status': 'matched', 'raw': raw, 'label': label, 'option_id': option.get('id')}
    return {'status': 'unmatched', 'raw': raw, 'label': None, 'option_id': None}


def resolve_existing_human_value(
    row: dict[str, Any], item: dict[str, Any],
) -> dict[str, Any]:
    """Resolve and classify an explicitly mapped human answer/parameter value."""
    header = item.get('answer_column')
    raw = resolve_source_value(row, header)
    options = [*(item.get('answers') or []), *(item.get('options') or [])]
    if options:
        return match_answer_label(raw, options)
    if raw is None or not str(raw).strip():
        return {'status': 'blank', 'raw': '' if raw is None else str(raw), 'value': None}
    return {'status': 'matched', 'raw': str(raw), 'value': raw}


def format_title_abstract_context(
    row: dict[str, Any], citation_fields: dict[str, Any],
) -> str:
    title = resolve_source_value(row, citation_fields.get('title'))
    abstract = resolve_source_value(row, citation_fields.get('abstract'))
    excluded = {
        _normalize_key(str(citation_fields.get('title') or '')),
        _normalize_key(str(citation_fields.get('abstract') or '')),
    }
    pairs = []
    for header in citation_fields.get('l1_include') or []:
        if _normalize_key(str(header)) in excluded:
            continue
        value = resolve_source_value(row, header)
        if value is None or not str(value).strip():
            continue
        pairs.append(f"{header}: {value}")
    other = '; '.join(pairs) or '(none configured)'
    return f"Title: {title or ''}\nAbstract: {abstract or ''}\nOther fields: {other}"


def format_item_context(item: dict[str, Any]) -> str:
    parts = [str(item.get('question') or item.get('name') or '').strip()]
    if item.get('description'):
        parts.append(f"Description: {item['description']}")
    if item.get('context'):
        parts.append(f"Context: {item['context']}")
    if item.get('critical_prompt_additions'):
        parts.append(
            f"Critical prompt additions: {item['critical_prompt_additions']}",
        )
    if item.get('unit_instructions'):
        parts.append(f"Units: {item['unit_instructions']}")
    if item.get('calculation'):
        parts.append(f"Calculation: {item['calculation']}")
    if item.get('selection_mode'):
        parts.append(f"Answer cardinality: {item['selection_mode']}")
    options = [*(item.get('answers') or []), *(item.get('options') or [])]
    if options:
        parts.append(
            'Answer-specific guidance:\n' + '\n'.join(
                f"- {option.get('label')}: {option.get('context') or '(none)'}" for option in options
            ),
        )
    if item.get('trigger', {}).get('all'):
        parts.append(
            f"Visible only when trigger conditions are met: {item['trigger']['all']}",
        )
    return '\n'.join(part for part in parts if part)
