"""Discover user-authored citation columns for criteria configuration."""
from __future__ import annotations

import re
from typing import Any

from .cit_db_service import cits_dp_service

SYSTEM_NAMES = {
    'id', 'combined_citation',
    'human_l1_decision', 'human_l2_decision',
}
SYSTEM_PREFIXES = ('llm_', 'human_', 'fulltext', 'parameters_', 'l1_', 'l2_')


def _is_user_field(name: str) -> bool:
    folded = name.casefold()
    return folded not in SYSTEM_NAMES and not any(folded.startswith(prefix) for prefix in SYSTEM_PREFIXES)


def _doi_score(name: str) -> int:
    tokens = [
        token for token in re.split(
            r'[^a-z0-9]+', name.casefold(),
        ) if token
    ]
    if name.casefold() == 'doi':
        return 100
    if 'doi' in tokens:
        return 80
    if 'digital' in tokens and 'object' in tokens and 'identifier' in tokens:
        return 60
    return 0


def build_citation_field_contract(review: dict[str, Any], columns: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for column in columns:
        name = str(
            column.get('column_name')
            or column.get('name') or '',
        ).strip()
        if not name or not _is_user_field(name):
            continue
        score = _doi_score(name)
        fields.append({
            'name': name, 'data_type': str(
                column.get('data_type') or 'text',
            ), 'doi_likelihood': score,
        })

    criteria = review.get('criteria') if isinstance(
        review.get(
            'criteria',
        ), dict,
    ) else review.get('criteria_parsed') or {}
    configured = criteria.get('citation_fields') if isinstance(
        criteria.get('citation_fields'), dict,
    ) else {}
    selected = [
        str(value) for value in configured.get(
            'l1_include',
        ) or criteria.get('include') or []
    ]
    doi = configured.get('doi')
    available = {field['name'] for field in fields}
    unavailable = [
        value for value in [*selected, doi]
        if value and value not in available
    ]
    suggestions = [
        field['name'] for field in sorted(
            fields, key=lambda field: -field['doi_likelihood'],
        ) if field['doi_likelihood'] > 0
    ]
    return {'fields': fields, 'doi_suggestions': suggestions, 'unavailable_configured_fields': list(dict.fromkeys(unavailable))}


def discover_citation_fields(review: dict[str, Any]) -> dict[str, Any]:
    table_name = (review.get('screening_db') or {}).get('table_name')
    columns = cits_dp_service.get_table_columns(
        table_name,
    ) if table_name else []
    return build_citation_field_contract(review, columns)
