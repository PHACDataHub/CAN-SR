"""Discover user-authored citation columns for criteria configuration."""
from __future__ import annotations

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


def build_citation_field_contract(review: dict[str, Any], columns: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for column in columns:
        name = str(
            column.get('column_name')
            or column.get('name') or '',
        ).strip()
        if not name or not _is_user_field(name):
            continue
        fields.append({
            'name': name, 'data_type': str(
                column.get('data_type') or 'text',
            ),
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
    title = configured.get('title')
    abstract = configured.get('abstract')
    available = {field['name'] for field in fields}
    unavailable = [
        value for value in [*selected, title, abstract, doi]
        if value and value not in available
    ]
    return {
        'fields': fields,
        'unavailable_configured_fields': list(dict.fromkeys(unavailable)),
    }


def discover_citation_fields(review: dict[str, Any]) -> dict[str, Any]:
    table_name = (review.get('screening_db') or {}).get('table_name')
    columns = cits_dp_service.get_table_columns(
        table_name,
    ) if table_name else []
    return build_citation_field_contract(review, columns)
