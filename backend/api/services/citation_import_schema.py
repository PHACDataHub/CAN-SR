"""Allowlisted schema policy for citation import preview reconciliation.

Dynamic citation tables have operational columns alongside user-imported source
fields. This module is the single source of truth for fields a preview may map
to and for identifiers a future reconciliation transaction may create.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CitationImportField:
    key: str
    physical_column: str
    postgres_type: str
    required: bool = False
    commit_supported: bool = False


# Optional fields are registered now so preview/reconciliation work has one
# explicit vocabulary. They remain unavailable to mapping decisions until the
# commit transaction can safely reconcile and insert them.
CITATION_IMPORT_FIELDS: dict[str, CitationImportField] = {
    'title': CitationImportField('title', 'title', 'TEXT', required=True, commit_supported=True),
    'abstract': CitationImportField('abstract', 'abstract', 'TEXT', required=True, commit_supported=True),
    'doi': CitationImportField('doi', 'doi', 'TEXT'),
    'authors': CitationImportField('authors', 'authors', 'TEXT'),
    'journal': CitationImportField('journal', 'journal', 'TEXT'),
    'year': CitationImportField('year', 'year', 'TEXT'),
    'keywords': CitationImportField('keywords', 'keywords', 'TEXT'),
    'url': CitationImportField('url', 'url', 'TEXT'),
    'type': CitationImportField('type', 'type', 'TEXT'),
}

REQUIRED_IMPORT_FIELD_KEYS = tuple(
    field.key for field in CITATION_IMPORT_FIELDS.values() if field.required
)
COMMIT_SUPPORTED_FIELD_KEYS = tuple(
    field.key for field in CITATION_IMPORT_FIELDS.values() if field.commit_supported
)

# These are created by the dynamic-table lifecycle or used by operational
# workflows. Imports may neither overwrite them nor create ambiguous names.
PROTECTED_CITATION_COLUMNS = frozenset({
    'id', 'cit_id', 'created_at', 'updated_at', 'fulltext_url', 'fulltext',
    'fulltext_md5', 'pdf_link_status', 'pdf_link_reason', 'pdf_link_source',
    'pdf_link_url', 'pdf_link_last_checked_at', 'pdf_link_error',
    'pdf_link_doi_source', 'l1_validated_by', 'l1_validated_at',
    'l2_validated_by', 'l2_validated_at', 'parameters_validated_by',
    'parameters_validated_at',
})
PROTECTED_CITATION_COLUMN_PREFIXES = ('llm_', 'human_', 'review_', 'system_')
ALLOWED_ADDITIONAL_FIELD_TYPES = frozenset({'text'})
_IDENTIFIER_RE = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')


def is_protected_citation_column(column: str) -> bool:
    normalized = str(column or '').strip().lower()
    return normalized in PROTECTED_CITATION_COLUMNS or normalized.startswith(PROTECTED_CITATION_COLUMN_PREFIXES)


def safe_additional_field_name(source_column: str, existing_columns: Iterable[str] = ()) -> str:
    """Return a deterministic safe new physical name or reject a collision.

    A future commit transaction must call this before interpolating an approved
    additional-column identifier into `ALTER TABLE` SQL.
    """
    source = str(source_column or '').strip()
    if not source:
        raise ValueError('Additional field source column is required')
    normalized = re.sub(r'[^a-z0-9]+', '_', source.lower()).strip('_')
    if not normalized:
        raise ValueError('Additional field source column has no usable name')
    candidate = f'import_{normalized}'[:63]
    existing = {str(column).lower() for column in existing_columns}
    if not _IDENTIFIER_RE.fullmatch(candidate):
        raise ValueError(
            'Additional field name is not a safe PostgreSQL identifier',
        )
    if is_protected_citation_column(candidate) or candidate in existing:
        raise ValueError(
            f'Additional field name collides with an existing or protected column: {candidate}',
        )
    return candidate
