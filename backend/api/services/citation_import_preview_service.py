"""Parse, validate, encrypt, and stage citation import previews without citation writes."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from cryptography.fernet import Fernet

from .citation_import_schema import COMMIT_SUPPORTED_FIELD_KEYS
from .citation_import_schema import REQUIRED_IMPORT_FIELD_KEYS

try:
    import rispy  # type: ignore
except Exception:  # pragma: no cover
    rispy = None

try:
    from .postgres_auth import postgres_server
except ModuleNotFoundError:  # Optional driver in isolated unit-test tooling.
    postgres_server = None


_REQUIRED_FIELDS = REQUIRED_IMPORT_FIELD_KEYS
_CANONICAL_RIS_COLUMNS = (
    'Title', 'Abstract', 'Keywords',
    'Journal', 'Year', 'Authors', 'DOI', 'Type', 'URL',
)
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')
_MAPPING_DECISION_VERSION = 1
_EXTERNAL_ID_HEADER_NAMESPACES = {
    'pmid': 'pubmed',
    'pubmedid': 'pubmed',
    'pubmedidentifier': 'pubmed',
    'embaseid': 'embase',
    'embasenumber': 'embase',
    'scopuseid': 'scopus',
    'eid': 'scopus',
    'webofscienceid': 'web_of_science',
    'webofscienceaccessionnumber': 'web_of_science',
    'wosid': 'web_of_science',
    'wosaccessionnumber': 'web_of_science',
}


def _initial_citation_table_name(sr_id: str, preview_id: str) -> str:
    """Return a deterministic, safe dynamic-table name for an initial import."""
    review_hash = hashlib.sha256(sr_id.encode('utf-8')).hexdigest()[:12]
    preview_prefix = preview_id.replace('-', '')[:12]
    return f'sr_{review_hash}_{preview_prefix}_cit'


def _create_initial_citation_table(cur, table_name: str) -> None:
    """Create the compatible minimum physical schema inside the caller transaction."""
    cur.execute(
        f'''CREATE TABLE "{table_name}" (
            id SERIAL PRIMARY KEY,
            "title" TEXT,
            "abstract" TEXT,
            "cit_id" TEXT,
            "fulltext_url" TEXT,
            "fulltext" TEXT,
            "fulltext_md5" TEXT,
            "pdf_link_status" TEXT,
            "pdf_link_reason" TEXT,
            "pdf_link_source" TEXT,
            "pdf_link_url" TEXT,
            "pdf_link_last_checked_at" TIMESTAMP WITH TIME ZONE,
            "pdf_link_error" TEXT,
            "pdf_link_doi_source" TEXT,
            "l1_validated_by" TEXT,
            "l1_validated_at" TIMESTAMP WITH TIME ZONE,
            "l2_validated_by" TEXT,
            "l2_validated_at" TIMESTAMP WITH TIME ZONE,
            "parameters_validated_by" TEXT,
            "parameters_validated_at" TIMESTAMP WITH TIME ZONE,
            "created_at" TIMESTAMP WITH TIME ZONE DEFAULT now()
        )''',
    )


def _normalized_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (value or '').strip().lower())


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize PostgreSQL JSONB values from either native or string adapters."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError('Stored preview metadata is invalid')


def _isoformat(value: Any) -> str:
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _mapping_decision(
    mapping: dict[str, Any], excluded_source_columns: list[str],
    source_columns: list[str], row_count: int,
    excluded_ambiguous_row_numbers: list[int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a canonical mapping decision and return refreshed diagnostics.

    Additional physical citation fields require explicit schema reconciliation,
    which deliberately is not part of this endpoint. Every source column is
    therefore mapped to title/abstract or explicitly excluded.
    """
    if not isinstance(mapping, dict) or set(mapping) != set(COMMIT_SUPPORTED_FIELD_KEYS):
        raise ValueError(
            'approved_mapping must contain exactly the currently commit-supported fields: title and abstract',
        )
    if not isinstance(excluded_source_columns, list) or any(not isinstance(value, str) for value in excluded_source_columns):
        raise ValueError(
            'excluded_source_columns must be an array of source column names',
        )
    if len(set(excluded_source_columns)) != len(excluded_source_columns):
        raise ValueError('excluded_source_columns must not contain duplicates')
    if any(column not in source_columns for column in excluded_source_columns):
        raise ValueError(
            'excluded_source_columns contains an unknown source column',
        )
    mapped_columns: list[str] = []
    for field in _REQUIRED_FIELDS:
        column = mapping[field]
        if column is not None and (not isinstance(column, str) or column not in source_columns):
            raise ValueError(
                f'approved_mapping.{field} must reference a source column or null',
            )
        if column:
            mapped_columns.append(column)
    if len(set(mapped_columns)) != len(mapped_columns):
        raise ValueError(
            'A source column cannot map to more than one supported field',
        )
    unclassified = set(source_columns) - set(mapped_columns) - \
        set(excluded_source_columns)
    if unclassified:
        raise ValueError(
            f'Every source column must be mapped or explicitly excluded: {sorted(unclassified)}',
        )
    excluded_ambiguous_row_numbers = excluded_ambiguous_row_numbers or []
    if (
        any(
            not isinstance(row_number, int) or isinstance(row_number, bool)
            for row_number in excluded_ambiguous_row_numbers
        )
        or len(set(excluded_ambiguous_row_numbers)) != len(excluded_ambiguous_row_numbers)
        or any(row_number < 1 or row_number > row_count for row_number in excluded_ambiguous_row_numbers)
    ):
        raise ValueError(
            'excluded_ambiguous_row_numbers must contain unique source row numbers',
        )
    missing_fields = [
        field for field in _REQUIRED_FIELDS if not mapping[field]
    ]
    missing_row_counts = {
        field: row_count if field in missing_fields else 0 for field in _REQUIRED_FIELDS
    }
    report = {
        'row_count': row_count,
        'source_columns': source_columns,
        'missing_required_fields': missing_fields,
        'missing_required_value_counts': missing_row_counts,
        'unclassified_source_columns': [],
        'valid_for_commit': not missing_fields and all(count == 0 for count in missing_row_counts.values()),
    }
    decision = {
        'version': _MAPPING_DECISION_VERSION,
        'approved_mapping': mapping,
        'excluded_source_columns': excluded_source_columns,
        'excluded_ambiguous_row_numbers': sorted(excluded_ambiguous_row_numbers),
    }
    return decision, report


def _revalidated_mapping_report(
    mapping: dict[str, str | None], excluded_source_columns: list[str],
    source_columns: list[str], rows: list[dict[str, Any]],
    excluded_ambiguous_row_numbers: list[int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recalculate required-value diagnostics from staged rows for an approved mapping."""
    decision, report = _mapping_decision(
        mapping, excluded_source_columns, source_columns, len(
            rows,
        ), excluded_ambiguous_row_numbers,
    )
    for field, column in mapping.items():
        if column:
            report['missing_required_value_counts'][field] = sum(
                not isinstance(row, dict) or not str(
                    row.get(column) or '',
                ).strip()
                for row in rows
            )
    report['valid_for_commit'] = (
        not report['missing_required_fields']
        and all(count == 0 for count in report['missing_required_value_counts'].values())
    )
    return decision, report


def _bibliographic_fingerprint(title: Any, abstract: Any) -> str:
    """Versioned exact identity for the currently supported canonical import fields."""
    normalized = '\x1f'.join(
        re.sub(r'\s+', ' ', str(value or '').strip()).casefold()
        for value in (title, abstract)
    )
    return f'v1:{hashlib.sha256(normalized.encode("utf-8")).hexdigest()}'


def _normalized_doi(value: Any) -> str:
    """Return a stable DOI identity, without accepting a URL as a distinct DOI."""
    doi = str(value or '').strip()
    lowered = doi.casefold()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'doi:'):
        if lowered.startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    return doi.rstrip('.,;').casefold()


def _row_doi(row: dict[str, Any]) -> str:
    """Read DOI from a known source header; DOI is identity metadata, not a mapped field."""
    for column, value in row.items():
        if _normalized_name(column) in {'doi', 'digitalobjectidentifier'}:
            return _normalized_doi(value)
    return ''


def _normalized_external_id(namespace: str, value: Any) -> str:
    """Normalize an explicitly namespaced source identifier without crossing systems."""
    identifier = re.sub(r'\s+', '', str(value or '').strip())
    prefixes = {
        'pubmed': r'(?:pmid|pubmed(?:id|identifier)?):?',
        'embase': r'(?:embase(?:id|number)?):?',
        'scopus': r'(?:scopus(?:eid)?|eid):?',
        'web_of_science': r'(?:webofscience(?:id|accessionnumber)?|wos(?:id|accessionnumber)?):?',
    }
    return re.sub(f'^{prefixes[namespace]}', '', identifier, flags=re.IGNORECASE).casefold()


def _row_external_ids(row: dict[str, Any]) -> list[tuple[str, str]]:
    """Read recognized source headers into distinct external-ID namespaces."""
    identities: list[tuple[str, str]] = []
    for column, value in row.items():
        namespace = _EXTERNAL_ID_HEADER_NAMESPACES.get(
            _normalized_name(column),
        )
        if namespace:
            normalized = _normalized_external_id(namespace, value)
            if normalized and (namespace, normalized) not in identities:
                identities.append((namespace, normalized))
    return identities


def _identity_candidates(title: Any, abstract: Any, row: dict[str, Any]) -> list[tuple[str, str | None, str]]:
    """Return DOI, namespaced external IDs, then fingerprint exact identities."""
    fingerprint = _bibliographic_fingerprint(title, abstract)
    doi = _row_doi(row)
    external_ids = [
        ('external_id', namespace, value)
        for namespace, value in _row_external_ids(row)
    ]
    return ([('doi', None, doi)] if doi else []) + external_ids + [('bibliographic_fingerprint', None, fingerprint)]


def sniff_format(filename: str, raw_bytes: bytes) -> str:
    name = (filename or '').lower()
    if name.endswith('.csv'):
        return 'csv'
    if name.endswith('.ris') or name.endswith('.txt'):
        return 'ris'
    text = raw_bytes.decode('utf-8', errors='ignore').lower()
    return 'ris' if 'ty  -' in text and 'er  -' in text else 'csv'


def _decode(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw_bytes.decode('utf-8', errors='replace')


def _join(value: Any, separator: str = '; ') -> str:
    if isinstance(value, list):
        return separator.join(str(item) for item in value if str(item).strip())
    return '' if value is None else str(value)


def _year(value: Any) -> str:
    match = re.search(r'(?:19|20)\d{2}', str(value or ''))
    return match.group(0) if match else ''


def _ris_value(column: str, entry: dict[str, Any]) -> Any:
    key = column.lower()
    values = {
        'title': entry.get('title') or entry.get('primary_title') or entry.get('short_title'),
        'abstract': entry.get('abstract') or entry.get('notes_abstract') or _join(entry.get('notes'), '\n'),
        'keywords': _join(entry.get('keywords')),
        'journal': entry.get('secondary_title') or entry.get('journal_name'),
        'year': _year(entry.get('year') or entry.get('publication_year') or entry.get('date')),
        'authors': _join(entry.get('authors')),
        'doi': entry.get('doi'),
        'type': entry.get('type_of_reference'),
        'url': _join(entry.get('urls')),
    }
    return values.get(key, entry.get(key))


def parse_source(filename: str, raw_bytes: bytes) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Return source format, raw-header rows, and source columns."""
    source_format = sniff_format(filename, raw_bytes)
    text = _decode(raw_bytes)
    if source_format == 'csv':
        reader = csv.DictReader(io.StringIO(text))
        return source_format, list(reader), list(reader.fieldnames or [])
    if rispy is None:
        raise ValueError('RIS upload requested but rispy is not installed')
    entries = rispy.load(io.StringIO(text))
    rows = [
        {
            column: _ris_value(column, entry)
            for column in _CANONICAL_RIS_COLUMNS
        } for entry in entries
    ]
    return source_format, rows, list(_CANONICAL_RIS_COLUMNS)


def build_preview(filename: str, raw_bytes: bytes) -> dict[str, Any]:
    """Build deterministic parse/mapping diagnostics without persistence."""
    if not raw_bytes:
        raise ValueError('Uploaded file is empty')
    source_format, rows, columns = parse_source(filename, raw_bytes)
    if not columns:
        raise ValueError('No columns found in upload')

    normalized_columns = {
        _normalized_name(
            column,
        ): column for column in columns if column
    }
    mapping = {
        field: normalized_columns.get(_normalized_name(field))
        for field in _REQUIRED_FIELDS
    }
    missing_fields = [field for field, column in mapping.items() if not column]
    missing_row_counts = {
        field: sum(
            not str(row.get(column) or '').strip()
            for row in rows
        ) if column else len(rows)
        for field, column in mapping.items()
    }
    canonical_schema = json.dumps(
        columns, ensure_ascii=False, separators=(',', ':'),
    )
    return {
        'source_format': source_format,
        'source_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'schema_fingerprint': f"sha256:{hashlib.sha256(canonical_schema.encode()).hexdigest()}",
        'proposed_mapping': mapping,
        'validation_report': {
            'row_count': len(rows),
            'source_columns': columns,
            'missing_required_fields': missing_fields,
            'missing_required_value_counts': missing_row_counts,
            'unclassified_source_columns': [
                column for column in columns if column not in set(mapping.values())
            ],
            'valid_for_commit': not missing_fields and all(count == 0 for count in missing_row_counts.values()),
        },
        'normalized_rows': rows,
    }


class CitationImportPreviewRepository:
    """Minimal metadata repository; raw staged content remains in encrypted storage."""

    def __init__(self, connection_provider=None):
        self.connection_provider = connection_provider

    def create(self, record: dict[str, Any]) -> None:
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO citation_import_previews
                   (id, sr_id, citation_table_name, source_sha256, schema_fingerprint,
                    proposed_mapping, validation_report, encrypted_staging_locator,
                    staging_expires_at, commit_key, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)""",
                (
                    record['id'], record['sr_id'], record['citation_table_name'],
                    record['source_sha256'], record['schema_fingerprint'],
                    json.dumps(record['proposed_mapping']), json.dumps(
                        record['validation_report'],
                    ),
                    record['encrypted_staging_locator'], record['staging_expires_at'],
                    record['commit_key'], record['created_by'],
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def reconcile(
        self, sr_id: str, citation_table_name: str | None,
        rows: list[dict[str, Any]], mapping: dict[str, str | None],
        excluded_ambiguous_row_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """Classify preview rows against durable exact identities without mutating citations."""
        counts = {
            'new': 0, 'existing_exact_match': 0,
            'ambiguous': 0, 'excluded_ambiguous': 0, 'invalid': 0,
        }
        examples: list[dict[str, Any]] = []
        ambiguous_details: list[dict[str, Any]] = []
        excluded_ambiguous_row_numbers = set(
            excluded_ambiguous_row_numbers or [],
        )
        ambiguous_row_numbers: list[int] = []
        title_column, abstract_column = mapping.get(
            'title',
        ), mapping.get('abstract')
        if not title_column or not abstract_column:
            return {'counts': counts, 'examples': examples}
        identities: dict[tuple[str, str | None, str], list[int]] = {}
        if citation_table_name:
            provider = self.connection_provider or postgres_server
            if provider is None:
                raise RuntimeError('PostgreSQL driver is not available')
            conn = provider.conn
            cur = conn.cursor()
            try:
                cur.execute(
                    """SELECT identity_kind, identifier_namespace, normalized_value, citation_id
                       FROM citation_identities
                       WHERE sr_id = %s AND citation_table_name = %s
                          AND identity_kind IN ('doi', 'external_id', 'bibliographic_fingerprint')""",
                    (sr_id, citation_table_name),
                )
                for result in cur.fetchall():
                    # Accept legacy three-column mock fixtures while production always returns four.
                    if len(result) == 3:
                        kind, value, citation_id = result
                        namespace = None
                    else:
                        kind, namespace, value, citation_id = result
                    identities.setdefault(
                        (
                            str(kind), str(namespace) if namespace else None, str(
                                value,
                            ),
                        ), [],
                    ).append(int(citation_id))
            finally:
                cur.close()
        seen: dict[tuple[str, str | None, str], int] = {}
        next_provisional_citation_id = -1
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not str(row.get(title_column) or '').strip() or not str(row.get(abstract_column) or '').strip():
                outcome, identity = 'invalid', None
            else:
                candidates = _identity_candidates(
                    row[title_column], row[abstract_column], row,
                )
                candidate_matches = {
                    candidate: sorted(
                        set(identities.get(candidate, []))
                        | ({seen[candidate]} if candidate in seen else set()),
                    )
                    for candidate in candidates
                }
                matches = {
                    citation_id
                    for candidate_citation_ids in candidate_matches.values()
                    for citation_id in candidate_citation_ids
                }
                if len(matches) > 1:
                    ambiguous_row_numbers.append(index + 1)
                    if len(ambiguous_details) < 25:
                        ambiguous_details.append({
                            'row_number': index + 1,
                            'matches': [
                                {
                                    'identity_kind': kind,
                                    'identifier_namespace': namespace,
                                    'normalized_value': normalized_value,
                                    'citation_ids': citation_ids,
                                }
                                for (kind, namespace, normalized_value), citation_ids in candidate_matches.items()
                                if citation_ids
                            ],
                        })
                    outcome, identity = (
                        ('excluded_ambiguous', None)
                        if index + 1 in excluded_ambiguous_row_numbers else ('ambiguous', None)
                    )
                elif matches:
                    outcome, identity = 'existing_exact_match', next(
                        iter(matches),
                    ) if matches else None
                else:
                    outcome, identity = 'new', None
                    identity = next_provisional_citation_id
                    next_provisional_citation_id -= 1
                seen.update({candidate: identity for candidate in candidates})
            counts[outcome] += 1
            if len(examples) < 10:
                example = {'row_number': index + 1, 'outcome': outcome}
                if identity is not None and identity > 0:
                    example['citation_id'] = identity
                examples.append(example)
        if excluded_ambiguous_row_numbers - set(ambiguous_row_numbers):
            raise ValueError(
                'Only currently ambiguous source rows may be excluded',
            )
        return {
            'counts': counts,
            'examples': examples,
            'ambiguous_row_numbers': ambiguous_row_numbers,
            'ambiguous_details': ambiguous_details,
        }

    def cancel(self, preview_id: str, sr_id: str, actor_id: str) -> str | None:
        """Cancel one owned, uncommitted preview and return its staging locator."""
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """UPDATE citation_import_previews
                   SET cancelled_at = CURRENT_TIMESTAMP
                   WHERE id = %s AND sr_id = %s AND created_by = %s
                     AND cancelled_at IS NULL AND committed_batch_id IS NULL
                     AND staging_expires_at > CURRENT_TIMESTAMP
                   RETURNING encrypted_staging_locator""",
                (preview_id, sr_id, actor_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            conn.commit()
            return str(row[0])
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def get_active(self, preview_id: str, sr_id: str, actor_id: str) -> dict[str, Any] | None:
        """Return active owned metadata only; encrypted staging is never selected."""
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT id, citation_table_name, source_sha256, schema_fingerprint,
                          proposed_mapping, validation_report, staging_expires_at, created_at
                   FROM citation_import_previews
                   WHERE id = %s AND sr_id = %s AND created_by = %s
                     AND cancelled_at IS NULL AND committed_batch_id IS NULL
                     AND staging_expires_at > CURRENT_TIMESTAMP""",
                (preview_id, sr_id, actor_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                'id': str(row[0]), 'citation_table_name': row[1],
                'source_sha256': row[2], 'schema_fingerprint': row[3],
                'proposed_mapping': _json_object(row[4]),
                'validation_report': _json_object(row[5]),
                'staging_expires_at': _isoformat(row[6]), 'created_at': _isoformat(row[7]),
            }
        finally:
            cur.close()

    def update_mapping_decision(
        self, preview_id: str, sr_id: str, actor_id: str,
        approved_mapping: dict[str, str | None],
        excluded_source_columns: list[str],
        refreshed_report: dict[str, Any],
        excluded_ambiguous_row_numbers: list[int] | None = None,
    ) -> dict[str, Any] | None:
        """Persist an active owner's canonical decision and refreshed diagnostics."""
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT proposed_mapping, validation_report FROM citation_import_previews
                   WHERE id = %s AND sr_id = %s AND created_by = %s
                     AND cancelled_at IS NULL AND committed_batch_id IS NULL
                     AND staging_expires_at > CURRENT_TIMESTAMP
                   FOR UPDATE""",
                (preview_id, sr_id, actor_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            prior_report = _json_object(row[1])
            source_columns = prior_report.get('source_columns')
            row_count = prior_report.get('row_count')
            if not isinstance(source_columns, list) or not all(isinstance(value, str) for value in source_columns) or not isinstance(row_count, int):
                raise ValueError(
                    'Stored preview validation metadata is invalid',
                )
            decision, _expected_report = _mapping_decision(
                approved_mapping, excluded_source_columns, source_columns, row_count,
                excluded_ambiguous_row_numbers,
            )
            if refreshed_report.get('row_count') != row_count or refreshed_report.get('source_columns') != source_columns:
                raise ValueError(
                    'Refreshed preview validation metadata does not match the staged preview',
                )
            report = refreshed_report
            cur.execute(
                """UPDATE citation_import_previews
                   SET proposed_mapping = %s::jsonb, mapping_decision = %s::jsonb,
                       validation_report = %s::jsonb
                   WHERE id = %s""",
                (
                    json.dumps(approved_mapping), json.dumps(
                        decision,
                    ), json.dumps(report), preview_id,
                ),
            )
            conn.commit()
            return {'proposed_mapping': approved_mapping, 'mapping_decision': decision, 'validation_report': report}
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def get_staging_locator(self, preview_id: str, sr_id: str, actor_id: str) -> str | None:
        """Internal owned lookup for commit; callers never receive this locator."""
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT encrypted_staging_locator FROM citation_import_previews
                   WHERE id = %s AND sr_id = %s AND created_by = %s""",
                (preview_id, sr_id, actor_id),
            )
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    def commit(
        self, preview_id: str, sr_id: str, actor_id: str, approved_mapping: dict[str, str | None],
        staged_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Commit verified staged rows and all provenance in one database transaction."""
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        conn = provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT citation_table_name, source_sha256, proposed_mapping, mapping_decision, validation_report,
                          committed_batch_id, cancelled_at, staging_expires_at
                   FROM citation_import_previews
                   WHERE id = %s AND sr_id = %s AND created_by = %s
                   FOR UPDATE""",
                (preview_id, sr_id, actor_id),
            )
            preview = cur.fetchone()
            if not preview:
                raise LookupError(
                    'Import preview was not found or is not owned by this user',
                )
            # Backward-compatible fixture shape before mapping_decision.
            if len(preview) == 7:
                table_name, source_sha256, proposed, report, committed_batch_id, cancelled_at, expires_at = preview
                mapping_decision = None
            else:
                table_name, source_sha256, proposed, mapping_decision, report, committed_batch_id, cancelled_at, expires_at = preview
            if committed_batch_id:
                cur.execute(
                    """SELECT inserted_count, existing_exact_match_count, invalid_count
                       FROM citation_import_batches WHERE id = %s""",
                    (str(committed_batch_id),),
                )
                counts = cur.fetchone()
                if not counts:
                    raise RuntimeError(
                        'Committed import preview has no batch record',
                    )
                conn.commit()
                return {
                    'id': preview_id, 'batch_id': str(committed_batch_id), 'idempotent': True,
                    'inserted_count': int(counts[0]), 'existing_exact_match_count': int(counts[1]),
                    'invalid_count': int(counts[2]),
                }
            if cancelled_at or expires_at <= datetime.now(timezone.utc):
                raise LookupError('Import preview is no longer active')
            if _json_object(proposed) != approved_mapping:
                raise ValueError(
                    'approved_mapping must exactly match the preview mapping',
                )
            decision_data = _json_object(
                mapping_decision,
            ) if mapping_decision else {}
            excluded_ambiguous_row_numbers = decision_data.get(
                'excluded_ambiguous_row_numbers', [],
            )
            if not isinstance(excluded_ambiguous_row_numbers, list) or any(
                not isinstance(row_number, int) or isinstance(row_number, bool)
                for row_number in excluded_ambiguous_row_numbers
            ):
                raise ValueError('Stored ambiguous-row resolution is invalid')
            report_data = _json_object(report)
            reconciliation = report_data.get('reconciliation')
            if isinstance(reconciliation, dict) and reconciliation.get('counts', {}).get('ambiguous', 0):
                raise ValueError(
                    'Preview has ambiguous exact citation identities',
                )
            if not report_data.get('valid_for_commit'):
                raise ValueError('Preview has blocking validation errors')
            raw_file = staged_payload.get('raw_file_base64')
            if not isinstance(raw_file, str) or hashlib.sha256(base64.b64decode(raw_file)).hexdigest() != source_sha256:
                raise ValueError(
                    'Staged preview source hash does not match preview metadata',
                )
            rows = staged_payload.get('normalized_rows')
            if not isinstance(rows, list):
                raise ValueError('Staged preview rows are invalid')
            title_column, abstract_column = approved_mapping.get(
                'title',
            ), approved_mapping.get('abstract')
            if not title_column or not abstract_column:
                raise ValueError(
                    'Approved title and abstract mappings are required',
                )
            if table_name and not _IDENT_RE.match(table_name):
                raise ValueError(
                    'Import preview contains an invalid citation table name',
                )
            cur.execute(
                """SELECT screening_db ->> 'table_name'
                   FROM systematic_reviews WHERE id = %s FOR UPDATE""",
                (sr_id,),
            )
            review = cur.fetchone()
            if not review:
                raise LookupError('Systematic review was not found')
            configured_table_name = review[0]
            is_initial_import = table_name is None
            if is_initial_import:
                if configured_table_name:
                    raise ValueError(
                        'A citation dataset was created while this initial import was being prepared',
                    )
                table_name = _initial_citation_table_name(sr_id, preview_id)
                _create_initial_citation_table(cur, table_name)
            elif configured_table_name != table_name:
                raise ValueError(
                    'Citation table is not configured for this systematic review',
                )
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = %s
                     AND column_name = ANY(%s)""",
                (table_name, ['id', 'title', 'abstract']),
            )
            if {item[0] for item in cur.fetchall()} != {'id', 'title', 'abstract'}:
                raise ValueError(
                    'Citation table lacks required canonical title and abstract columns',
                )

            cur.execute(
                """SELECT id, inserted_count, existing_exact_match_count, invalid_count
                   FROM citation_import_batches
                   WHERE sr_id = %s AND citation_table_name = %s AND content_sha256 = %s
                     AND state = 'committed'
                   FOR UPDATE""",
                (sr_id, table_name, source_sha256),
            )
            existing_batch = cur.fetchone()
            if existing_batch:
                existing_batch_id, inserted, existing, invalid = existing_batch
                cur.execute(
                    """UPDATE citation_import_previews SET committed_batch_id = %s
                       WHERE id = %s AND committed_batch_id IS NULL""",
                    (str(existing_batch_id), preview_id),
                )
                conn.commit()
                return {
                    'id': preview_id, 'batch_id': str(existing_batch_id), 'idempotent': True,
                    'inserted_count': int(inserted), 'existing_exact_match_count': int(existing),
                    'invalid_count': int(invalid),
                }

            batch_id = str(uuid.uuid4())
            filename = staged_payload.get('filename') if isinstance(
                staged_payload.get('filename'), str,
            ) else None
            cur.execute(
                """INSERT INTO citation_import_batches
                    (id, sr_id, citation_table_name, source_type, source_metadata, display_filename,
                     content_sha256, schema_fingerprint, mapping_decision, state, created_by)
                   SELECT %s, %s, %s, 'file', jsonb_build_object('source_format', %s), %s,
                          %s, schema_fingerprint, %s::jsonb, 'committed', %s
                   FROM citation_import_previews WHERE id = %s""",
                (
                    batch_id, sr_id, table_name, staged_payload.get(
                        'source_format',
                    ), filename,
                    source_sha256, json.dumps(
                        decision_data,
                    ), actor_id, preview_id,
                ),
            )
            inserted = existing = invalid = 0
            seen: dict[tuple[str, str | None, str], int] = {}
            for row_number, row in enumerate(rows, start=1):
                if row_number in excluded_ambiguous_row_numbers:
                    continue
                if not isinstance(row, dict):
                    invalid += 1
                    continue
                title, abstract = row.get(
                    title_column,
                ), row.get(abstract_column)
                if not str(title or '').strip() or not str(abstract or '').strip():
                    invalid += 1
                    continue
                doi = _row_doi(row)
                external_ids = _row_external_ids(row)
                fingerprint = _bibliographic_fingerprint(title, abstract)
                candidates = _identity_candidates(title, abstract, row)
                matches = {
                    seen[candidate]
                    for candidate in candidates if candidate in seen
                }
                for identity_kind, identifier_namespace, identity_value in candidates:
                    cur.execute(
                        'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                        (f'{sr_id}:{table_name}:{identity_kind}:{identifier_namespace or ""}:{identity_value}',),
                    )
                    cur.execute(
                        """SELECT citation_id FROM citation_identities
                           WHERE sr_id = %s AND citation_table_name = %s
                              AND identity_kind = %s
                              AND identifier_namespace IS NOT DISTINCT FROM %s
                              AND normalized_value = %s
                           LIMIT 1 FOR UPDATE""",
                        (
                            sr_id, table_name, identity_kind,
                            identifier_namespace, identity_value,
                        ),
                    )
                    match = cur.fetchone()
                    if match:
                        matches.add(int(match[0]))
                if len(matches) > 1:
                    raise ValueError(
                        'Import row has ambiguous exact citation identities',
                    )
                citation_id = next(iter(matches), None)
                if citation_id is not None:
                    existing += 1
                    seen.update(
                        {candidate: citation_id for candidate in candidates},
                    )
                    cur.execute(
                        """INSERT INTO citation_import_batch_memberships
                            (batch_id, sr_id, citation_table_name, citation_id, outcome, identity_snapshot)
                           VALUES (%s, %s, %s, %s, 'existing_exact_match', %s::jsonb)
                           ON CONFLICT (batch_id, citation_id) DO NOTHING""",
                        (
                            batch_id, sr_id, table_name, citation_id, json.dumps({
                                'identities': [
                                    {
                                        'kind': kind, 'namespace': namespace,
                                        'value': value,
                                    }
                                    for kind, namespace, value in candidates
                                ],
                            }),
                        ),
                    )
                    continue
                cur.execute(
                    f'INSERT INTO "{table_name}" ("title", "abstract") VALUES (%s, %s) RETURNING id',
                    (str(title), str(abstract)),
                )
                citation_id = int(cur.fetchone()[0])
                seen.update(
                    {candidate: citation_id for candidate in candidates},
                )
                inserted += 1
                cur.execute(
                    """INSERT INTO citation_identities
                        (id, sr_id, citation_table_name, citation_id, identity_kind, normalized_value, fingerprint_version)
                       VALUES (%s, %s, %s, %s, 'bibliographic_fingerprint', %s, 'v1')""",
                    (str(uuid.uuid4()), sr_id, table_name, citation_id, fingerprint),
                )
                if doi:
                    cur.execute(
                        """INSERT INTO citation_identities
                            (id, sr_id, citation_table_name, citation_id, identity_kind, normalized_value)
                           VALUES (%s, %s, %s, %s, 'doi', %s)""",
                        (str(uuid.uuid4()), sr_id, table_name, citation_id, doi),
                    )
                for identifier_namespace, identity_value in external_ids:
                    cur.execute(
                        """INSERT INTO citation_identities
                            (id, sr_id, citation_table_name, citation_id, identity_kind,
                             identifier_namespace, normalized_value)
                           VALUES (%s, %s, %s, %s, 'external_id', %s, %s)""",
                        (
                            str(uuid.uuid4()), sr_id, table_name, citation_id,
                            identifier_namespace, identity_value,
                        ),
                    )
                cur.execute(
                    """INSERT INTO citation_import_batch_memberships
                        (batch_id, sr_id, citation_table_name, citation_id, outcome, identity_snapshot)
                       VALUES (%s, %s, %s, %s, 'inserted', %s::jsonb)""",
                    (
                        batch_id, sr_id, table_name, citation_id, json.dumps({
                            'bibliographic_fingerprint': fingerprint,
                            **({'doi': doi} if doi else {}),
                            **({'external_ids': dict(external_ids)} if external_ids else {}),
                        }),
                    ),
                )
            cur.execute(
                """UPDATE citation_import_batches SET inserted_count = %s, existing_exact_match_count = %s,
                          invalid_count = %s, committed_at = CURRENT_TIMESTAMP WHERE id = %s""",
                (inserted, existing, invalid, batch_id),
            )
            cur.execute(
                """UPDATE citation_import_previews SET committed_batch_id = %s
                   WHERE id = %s AND committed_batch_id IS NULL""",
                (batch_id, preview_id),
            )
            if is_initial_import:
                cur.execute(
                    """UPDATE systematic_reviews
                       SET screening_db = jsonb_build_object(
                               'table_name', %s,
                               'created_at', CURRENT_TIMESTAMP,
                               'rows', %s
                           ),
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s
                         AND (screening_db IS NULL OR screening_db ->> 'table_name' IS NULL)""",
                    (table_name, inserted, sr_id),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        'Initial citation dataset could not be registered for this review',
                    )
            cur.execute(
                """INSERT INTO citation_audit_events
                    (id, sr_id, citation_table_name, batch_id, event_type, actor_id, details)
                   VALUES (%s, %s, %s, %s, 'import_committed', %s,
                           jsonb_build_object('inserted_count', %s, 'existing_exact_match_count', %s, 'invalid_count', %s))""",
                (
                    str(uuid.uuid4()), sr_id, table_name, batch_id,
                    actor_id, inserted, existing, invalid,
                ),
            )
            conn.commit()
            return {
                'id': preview_id, 'batch_id': batch_id, 'idempotent': False, 'inserted_count': inserted,
                'existing_exact_match_count': existing, 'invalid_count': invalid,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


class CitationImportPreviewService:
    def __init__(self, storage, repository=None, *, secret_key: str, ttl_minutes: int = 1440):
        if not storage:
            raise ValueError(
                'Encrypted preview staging storage is not configured',
            )
        self.storage = storage
        self.repository = repository or CitationImportPreviewRepository()
        self.ttl_minutes = ttl_minutes
        self._fernet = Fernet(
            base64.urlsafe_b64encode(
                hashlib.sha256(secret_key.encode()).digest(),
            ),
        )

    async def create(
        self, *, sr_id: str, citation_table_name: str | None, filename: str,
        raw_bytes: bytes, commit_key: str, actor_id: str,
    ) -> dict[str, Any]:
        if not commit_key or not actor_id:
            raise ValueError('commit_key and actor_id are required')
        preview = build_preview(filename, raw_bytes)
        preview['validation_report']['reconciliation'] = self.repository.reconcile(
            sr_id, citation_table_name, preview['normalized_rows'], preview['proposed_mapping'],
        )
        preview_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + \
            timedelta(minutes=self.ttl_minutes)
        locator = f'{self.storage.container_name}/citation-import-previews/{sr_id}/{preview_id}.fernet'
        staged_payload = json.dumps(
            {
                'filename': filename, 'source_format': preview['source_format'],
                'raw_file_base64': base64.b64encode(raw_bytes).decode('ascii'),
                'normalized_rows': preview['normalized_rows'],
            }, ensure_ascii=False, separators=(',', ':'),
        ).encode()
        encrypted = self._fernet.encrypt(staged_payload)
        if not await self.storage.put_bytes_by_path(locator, encrypted, 'application/octet-stream'):
            raise RuntimeError('Failed to stage encrypted import preview')
        record = {
            'id': preview_id, 'sr_id': sr_id, 'citation_table_name': citation_table_name,
            'source_sha256': preview['source_sha256'], 'schema_fingerprint': preview['schema_fingerprint'],
            'proposed_mapping': preview['proposed_mapping'], 'validation_report': preview['validation_report'],
            'encrypted_staging_locator': locator, 'staging_expires_at': expires_at,
            'commit_key': commit_key, 'created_by': actor_id,
        }
        try:
            self.repository.create(record)
        except Exception:
            try:
                await self.storage.delete_by_path(locator)
            finally:
                raise
        return {
            'id': preview_id, 'source_format': preview['source_format'],
            'source_sha256': preview['source_sha256'], 'schema_fingerprint': preview['schema_fingerprint'],
            'proposed_mapping': preview['proposed_mapping'], 'validation_report': preview['validation_report'],
            'staging_expires_at': expires_at.isoformat(),
        }

    async def cancel(self, *, preview_id: str, sr_id: str, actor_id: str) -> dict[str, Any]:
        """Cancel an owned preview and best-effort remove its ciphertext staging blob."""
        if not actor_id:
            raise ValueError('actor_id is required')
        try:
            preview_id = str(uuid.UUID(preview_id))
        except (TypeError, ValueError) as exc:
            raise ValueError('preview_id must be a UUID') from exc
        locator = self.repository.cancel(preview_id, sr_id, actor_id)
        if not locator:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        try:
            await self.storage.delete_by_path(locator)
            cleanup_pending = False
        except Exception:
            # The metadata transition remains final. A later cleanup job can retry
            # deletion of ciphertext for cancelled/expired previews.
            cleanup_pending = True
        return {'id': preview_id, 'cancelled': True, 'staging_cleanup_pending': cleanup_pending}

    def inspect(self, *, preview_id: str, sr_id: str, actor_id: str) -> dict[str, Any]:
        """Read active owned preview metadata without accessing staged ciphertext."""
        if not actor_id:
            raise ValueError('actor_id is required')
        try:
            preview_id = str(uuid.UUID(preview_id))
        except (TypeError, ValueError) as exc:
            raise ValueError('preview_id must be a UUID') from exc
        preview = self.repository.get_active(preview_id, sr_id, actor_id)
        if not preview:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        return preview

    async def update_mapping(
        self, *, preview_id: str, sr_id: str, actor_id: str,
        approved_mapping: dict[str, str | None],
        excluded_source_columns: list[str],
        excluded_ambiguous_row_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """Revalidate staged rows and save an active owner's mapping decision."""
        if not actor_id:
            raise ValueError('actor_id is required')
        try:
            preview_id = str(uuid.UUID(preview_id))
        except (TypeError, ValueError) as exc:
            raise ValueError('preview_id must be a UUID') from exc
        preview = self.repository.get_active(preview_id, sr_id, actor_id)
        if not preview:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        locator = self.repository.get_staging_locator(
            preview_id, sr_id, actor_id,
        )
        if not locator:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        encrypted, _name = await self.storage.get_bytes_by_path(locator)
        try:
            staged_payload = json.loads(self._fernet.decrypt(encrypted))
        except Exception as exc:
            raise ValueError('Staged import preview is unreadable') from exc
        rows = staged_payload.get('normalized_rows')
        if not isinstance(rows, list):
            raise ValueError('Staged preview rows are invalid')
        source_columns = preview['validation_report'].get('source_columns')
        if not isinstance(source_columns, list) or not all(isinstance(column, str) for column in source_columns):
            raise ValueError('Stored preview validation metadata is invalid')
        _decision, report = _revalidated_mapping_report(
            approved_mapping, excluded_source_columns, source_columns, rows,
            excluded_ambiguous_row_numbers,
        )
        report['reconciliation'] = self.repository.reconcile(
            sr_id, preview['citation_table_name'], rows, approved_mapping,
            excluded_ambiguous_row_numbers,
        )
        if report['reconciliation']['counts']['ambiguous']:
            report['valid_for_commit'] = False
        result = self.repository.update_mapping_decision(
            preview_id, sr_id, actor_id, approved_mapping, excluded_source_columns,
            report, _decision['excluded_ambiguous_row_numbers'],
        )
        if not result:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        return {'id': preview_id, **result}

    async def commit(
        self, *, preview_id: str, sr_id: str, actor_id: str,
        approved_mapping: dict[str, str | None],
    ) -> dict[str, Any]:
        """Decrypt staging then atomically commit an active owned preview."""
        if not actor_id:
            raise ValueError('actor_id is required')
        try:
            preview_id = str(uuid.UUID(preview_id))
        except (TypeError, ValueError) as exc:
            raise ValueError('preview_id must be a UUID') from exc
        if not isinstance(approved_mapping, dict):
            raise ValueError('approved_mapping must be an object')
        locator = self.repository.get_staging_locator(
            preview_id, sr_id, actor_id,
        )
        if not locator:
            raise LookupError(
                'Import preview was not found, is not owned by this user, or is already finalized',
            )
        encrypted, _ = await self.storage.get_bytes_by_path(locator)
        try:
            staged_payload = json.loads(self._fernet.decrypt(encrypted))
        except Exception as exc:
            raise ValueError(
                'Encrypted staged preview could not be decrypted',
            ) from exc
        return self.repository.commit(preview_id, sr_id, actor_id, approved_mapping, staged_payload)
