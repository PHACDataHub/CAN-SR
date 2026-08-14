"""Immediate, append-only citation file imports.

This service deliberately does not reconcile or deduplicate source rows.  Import
batch and identity metadata is retained for provenance, while the citation table
is extended with text columns as new source fields appear.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .citation_import_preview_service import _bibliographic_fingerprint
from .citation_import_preview_service import _normalized_doi
from .citation_import_preview_service import _row_external_ids
from .citation_import_schema import is_protected_citation_column
from .postgres_auth import postgres_server


_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def normalize_source_columns(source_columns: list[str]) -> dict[str, str]:
    """Map each non-empty source header to a unique safe physical column."""
    result: dict[str, str] = {}
    used: set[str] = set()
    for index, raw in enumerate(source_columns):
        source = str(raw or '').strip()
        if not source:
            source = f'column_{index + 1}'
        if source in result:
            continue
        normalized = re.sub(
            r'[^a-z0-9]+', '_', source.casefold(),
        ).strip('_') or f'column_{index + 1}'
        if normalized[0].isdigit():
            normalized = f'column_{normalized}'
        if normalized in {'id', 'title', 'abstract'} or is_protected_citation_column(normalized):
            normalized = f'import_{normalized}'
        normalized = normalized[:63]
        candidate = normalized
        suffix = 2
        while candidate in used or not _IDENTIFIER.fullmatch(candidate):
            tail = f'_{suffix}'
            candidate = f'{normalized[:63 - len(tail)]}{tail}'
            suffix += 1
        result[source] = candidate
        used.add(candidate)
    return result


def _has_value(row: dict[str, Any]) -> bool:
    return any(str(value or '').strip() for value in row.values())


class CitationImportService:
    def __init__(self, connection_provider=None):
        self.connection_provider = connection_provider or postgres_server

    def append_rows_sync(
        self,
        *,
        sr_id: str,
        table_name: str | None,
        source_format: str,
        filename: str,
        raw_bytes: bytes,
        rows: list[dict[str, Any]],
        source_columns: list[str],
        actor_id: str,
        commit_key: str,
        title_header: str | None = None,
        abstract_header: str | None = None,
    ) -> dict[str, Any]:
        if not actor_id or not commit_key:
            raise ValueError('actor_id and commit_key are required')
        if not source_columns:
            raise ValueError('No columns found in upload')
        names = normalize_source_columns(source_columns)
        by_normalized = {
            re.sub(r'[^a-z0-9]+', '', key.casefold()): key for key in names
        }

        def resolve_header(configured: str | None, aliases: tuple[str, ...]) -> str | None:
            if configured and configured in names:
                return configured
            for alias in aliases:
                if alias in by_normalized:
                    return by_normalized[alias]
            return None

        title_source = resolve_header(
            title_header, ('title', 'articletitle', 'primarytitle'),
        )
        abstract_source = resolve_header(
            abstract_header, ('abstract', 'summary', 'description'),
        )
        if not title_source or not abstract_source:
            missing = []
            if not title_source:
                missing.append('title')
            if not abstract_source:
                missing.append('abstract')
            raise ValueError(
                f"Missing required source headers: {', '.join(missing)}",
            )

        usable_rows = [
            row for row in rows if isinstance(
                row, dict,
            ) and _has_value(row)
        ]
        if any(not str(row.get(title_source) or '').strip() or not str(row.get(abstract_source) or '').strip() for row in usable_rows):
            raise ValueError(
                'Every non-blank row must contain a title and abstract value',
            )
        content_sha = hashlib.sha256(raw_bytes).hexdigest()
        conn = self.connection_provider.conn
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT id, citation_table_name, inserted_count, existing_exact_match_count,
                          invalid_count FROM citation_import_batches
                   WHERE sr_id = %s AND source_metadata ->> 'commit_key' = %s
                   ORDER BY created_at DESC LIMIT 1""", (sr_id, commit_key),
            )
            prior = cur.fetchone()
            if prior:
                conn.rollback()
                return {
                    'batch_id': str(prior[0]), 'table_name': prior[1], 'idempotent': True,
                    'rows_inserted': prior[2], 'invalid_count': prior[4],
                    'warnings': [],
                }

            if table_name:
                if not _IDENTIFIER.fullmatch(table_name):
                    raise ValueError('Invalid citation table name')
            else:
                table_name = f"sr_{hashlib.sha256(sr_id.encode()).hexdigest()[:12]}_{uuid.uuid4().hex[:12]}_cit"
                cur.execute(f'''CREATE TABLE "{table_name}" (
                    id SERIAL PRIMARY KEY, "title" TEXT, "abstract" TEXT,
                    "provenance" TEXT,
                    "cit_id" TEXT, "fulltext_url" TEXT, "fulltext" TEXT,
                    "fulltext_md5" TEXT, "pdf_link_status" TEXT,
                    "pdf_link_reason" TEXT, "pdf_link_source" TEXT,
                    "pdf_link_url" TEXT, "pdf_link_last_checked_at" TIMESTAMPTZ,
                    "pdf_link_error" TEXT, "pdf_link_doi_source" TEXT,
                    "l1_validated_by" TEXT, "l1_validated_at" TIMESTAMPTZ,
                    "l2_validated_by" TEXT, "l2_validated_at" TIMESTAMPTZ,
                    "parameters_validated_by" TEXT, "parameters_validated_at" TIMESTAMPTZ,
                    "created_at" TIMESTAMPTZ DEFAULT now())''')

            existing = set()
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = %s""", (table_name,),
            )
            existing.update(row[0] for row in cur.fetchall())
            physical = dict(names)
            physical[title_source] = 'title'
            physical[abstract_source] = 'abstract'
            physical['__provenance__'] = 'provenance'
            assigned: set[str] = set(existing)
            for source, column in list(physical.items()):
                if source == '__provenance__' or column in {'title', 'abstract'}:
                    physical[source] = 'provenance' if source == '__provenance__' else column
                    assigned.add(column)
                    continue
                candidate = column
                suffix = 2
                while candidate in assigned:
                    tail = f'_{suffix}'
                    candidate = f'{column[:63 - len(tail)]}{tail}'
                    suffix += 1
                physical[source] = candidate
                assigned.add(candidate)
            for column in set(physical.values()) - existing:
                if column not in existing:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column}" TEXT',
                    )

            batch_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO citation_import_batches
                    (id, sr_id, citation_table_name, source_type, source_metadata,
                     display_filename, content_sha256, schema_fingerprint, state, created_by)
                   VALUES (%s, %s, %s, 'file', %s::jsonb, %s, %s, %s, 'committed', %s)""",
                (
                    batch_id, sr_id, table_name, json.dumps(
                        {'commit_key': commit_key, 'source_format': source_format},
                    ),
                    filename, content_sha, 'sha256:' +
                    hashlib.sha256(
                        json.dumps(
                            source_columns,
                        ).encode(),
                    ).hexdigest(), actor_id,
                ),
            )
            insert_columns = list(dict.fromkeys(physical.values()))
            quoted = ', '.join(f'"{column}"' for column in insert_columns)
            placeholders = ', '.join(['%s'] * len(insert_columns))
            inserted = 0
            for row in usable_rows:
                values = [
                    filename if source == '__provenance__' else
                    (
                        str(row.get(source) or '') if row.get(
                            source,
                        ) is not None else None
                    )
                    for source, column in physical.items() if column in insert_columns
                ]
                cur.execute(
                    f'INSERT INTO "{table_name}" ({quoted}) VALUES ({placeholders}) RETURNING id', values,
                )
                citation_id = cur.fetchone()[0]
                inserted += 1
                fingerprint = _bibliographic_fingerprint(
                    row.get(title_source), row.get(abstract_source),
                )
                doi = next(
                    (
                        _normalized_doi(value) for source, value in row.items() if re.sub(
                            r'[^a-z0-9]+', '', source.casefold(),
                        ) in {'doi', 'digitalobjectidentifier'}
                    ), '',
                )
                identities = [('bibliographic_fingerprint', None, fingerprint)]
                if doi:
                    identities.append(('doi', None, doi))
                identities.extend(
                    ('external_id', namespace, value)
                    for namespace, value in _row_external_ids(row)
                )
                for kind, namespace, value in identities:
                    cur.execute(
                        """INSERT INTO citation_identities
                        (id, sr_id, citation_table_name, citation_id, identity_kind,
                         identifier_namespace, normalized_value, fingerprint_version)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING""",
                        (
                            str(
                                uuid.uuid4(),
                            ), sr_id, table_name, citation_id, kind, namespace,
                            value, 'v1' if kind == 'bibliographic_fingerprint' else None,
                        ),
                    )
                cur.execute(
                    """INSERT INTO citation_import_batch_memberships
                    (batch_id, sr_id, citation_table_name, citation_id, outcome, identity_snapshot)
                    VALUES (%s, %s, %s, %s, 'inserted', %s::jsonb)""",
                    (
                        batch_id, sr_id, table_name, citation_id, json.dumps(
                            {'bibliographic_fingerprint': fingerprint},
                        ),
                    ),
                )
            cur.execute(
                """UPDATE citation_import_batches SET inserted_count = %s,
                committed_at = CURRENT_TIMESTAMP WHERE id = %s""", (inserted, batch_id),
            )
            conn.commit()
            return {
                'batch_id': batch_id, 'table_name': table_name, 'idempotent': False,
                'rows_inserted': inserted, 'invalid_count': 0, 'warnings': [],
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_import_service = CitationImportService()
