"""Semantic, allowlist-only citation export policy and CSV generation."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from ..citations.export_models import CitationExportRequest
from ..citations.export_models import CitationExportSchema
from ..citations.export_models import ExportDimension
from ..citations.export_models import ExportGroup
from ..citations.export_models import ExportItem
from .cit_db_service import cits_dp_service, snake_case, snake_case_param


class ExportValidationError(ValueError):
    """A safe, client-visible export contract/configuration error."""


DENIED_NAME_PARTS = (
    'path', 'fulltext', 'raw', 'prompt', 'token', 'secret', 'credential',
    'connection', 'dsn', 'coord', 'bbox', 'page', 'table', 'figure', 'xml',
    'debug', 'error', 'job', 'artifact', 'cookie', 'authorization',
)

# Semantic id, label, physical aliases, output header, selected by default.
CITATION_FIELDS = (
    ('citation.id', 'Citation ID', ('id',), 'Citation ID', True),
    ('citation.title', 'Title', ('title',), 'Title', True),
    ('citation.abstract', 'Abstract', ('abstract',), 'Abstract', True),
    ('citation.authors', 'Authors', ('authors', 'author'), 'Authors', True),
    ('citation.journal', 'Journal', ('journal', 'secondary_title'), 'Journal', True),
    ('citation.year', 'Year', ('year', 'publication_year'), 'Year', True),
    ('citation.doi', 'DOI', ('doi',), 'DOI', True),
    ('citation.type', 'Reference type', ('type', 'type_of_reference'), 'Reference type', True),
    ('citation.keywords', 'Keywords', ('keywords',), 'Keywords', True),
    ('citation.notes', 'Notes', ('notes',), 'Notes', False),
)

SCREEN_DIMENSIONS = (
    ('human_answer', 'Human answers', True),
    ('ai_answer', 'AI answers', False),
    ('ai_explanation', 'AI explanations', False),
    ('confidence', 'Confidence', False),
    ('evidence', 'Evidence', False),
)
PARAM_DIMENSIONS = (
    ('human_value', 'Human extracted values', False),
    ('ai_value', 'AI extracted values', False),
    ('ai_explanation', 'AI explanations', False),
    ('evidence', 'Evidence', False),
)


@dataclass(frozen=True)
class OutputField:
    header: str
    column: str
    property: str | None = None


def screening_key(question: str) -> str:
    return snake_case(question, max_len=56) or 'criterion'


def parameter_key(name: str) -> str:
    column = snake_case_param(name)
    return column.removeprefix('llm_param_')


def _denied(name: str) -> bool:
    lowered = name.casefold()
    return any(part in lowered for part in DENIED_NAME_PARTS)


def _dimensions(spec) -> list[ExportDimension]:
    return [ExportDimension(id=i, label=label, default_selected=default) for i, label, default in spec]


class CitationExportService:
    def build_schema(
        self, sr: dict[str, Any], table_name: str, columns: list[dict[str, str]] | None = None,
    ) -> CitationExportSchema:
        columns = columns if columns is not None else cits_dp_service.get_table_columns(table_name)
        existing = {str(c['column_name']).casefold(): str(c['column_name']) for c in columns}

        citation_items: list[ExportItem] = []
        for semantic_id, label, aliases, _header, default in CITATION_FIELDS:
            physical = next((existing[a.casefold()] for a in aliases if a.casefold() in existing), None)
            if physical and not _denied(physical):
                citation_items.append(ExportItem(id=semantic_id, label=label, default_selected=default))

        cp = (sr or {}).get('criteria_parsed') or {}
        l1 = self._screen_items('l1', (cp.get('l1') or {}).get('questions') or [], existing)
        l2 = self._screen_items('l2', (cp.get('l2') or {}).get('questions') or [], existing)
        params = self._parameter_items(cp.get('parameters') or {}, existing)

        # A shared physical key in two current stages is ambiguous and must not be guessed.
        all_keys: dict[str, str] = {}
        for stage, questions in (
            ('l1', (cp.get('l1') or {}).get('questions') or []),
            ('l2', (cp.get('l2') or {}).get('questions') or []),
        ):
            for question in questions:
                key = screening_key(question)
                if key in all_keys:
                    raise ExportValidationError(
                        f'Current screening questions resolve to duplicate key {key!r}',
                    )
                all_keys[key] = stage

        return CitationExportSchema(groups=[
            ExportGroup(id='citation', label='Citation details', items=citation_items),
            ExportGroup(id='l1', label='L1 screening', dimensions=_dimensions(SCREEN_DIMENSIONS), items=l1),
            ExportGroup(id='l2', label='L2 screening', dimensions=_dimensions(SCREEN_DIMENSIONS), items=l2),
            ExportGroup(id='parameters', label='Extracted parameters', dimensions=_dimensions(PARAM_DIMENSIONS), items=params),
        ])

    def _screen_items(self, stage: str, questions: list[Any], existing: dict[str, str]) -> list[ExportItem]:
        items: list[ExportItem] = []
        seen: set[str] = set()
        for value in questions:
            if not isinstance(value, str) or not value.strip():
                continue
            key = screening_key(value)
            if key in seen:
                raise ExportValidationError(f'Current {stage.upper()} questions resolve to duplicate key {key!r}')
            seen.add(key)
            available = []
            if f'human_{key}'.casefold() in existing:
                available.append('human_answer')
            if f'llm_{key}'.casefold() in existing:
                available.extend(['ai_answer', 'ai_explanation', 'confidence', 'evidence'])
            items.append(ExportItem(
                id=f'{stage}.{key}', label=value,
                default_selected='human_answer' in available,
                available_dimensions=available,
            ))
        return items

    def _parameter_items(self, params: dict[str, Any], existing: dict[str, str]) -> list[ExportItem]:
        categories = params.get('categories') or []
        possible = params.get('possible_parameters') or []
        items: list[ExportItem] = []
        seen: set[str] = set()
        for index, names in enumerate(possible):
            category = str(categories[index]) if index < len(categories) else None
            for value in names if isinstance(names, list) else []:
                if not isinstance(value, str) or not value.strip():
                    continue
                key = parameter_key(value)
                if key in seen:
                    raise ExportValidationError(f'Current parameters resolve to duplicate key {key!r}')
                seen.add(key)
                available = []
                if f'human_param_{key}'.casefold() in existing:
                    available.append('human_value')
                if f'llm_param_{key}'.casefold() in existing:
                    available.extend(['ai_value', 'ai_explanation', 'evidence'])
                items.append(ExportItem(
                    id=f'parameters.{key}', label=value, category=category,
                    available_dimensions=available,
                ))
        return items

    def resolve(self, schema: CitationExportSchema, request: CitationExportRequest) -> list[OutputField]:
        groups = {group.id: group for group in schema.groups}
        selected: dict[str, tuple[set[str], set[str]]] = {}
        for selection in request.selections:
            if selection.group in selected:
                raise ExportValidationError(f'Duplicate selection group: {selection.group}')
            group = groups.get(selection.group)
            if not group:
                raise ExportValidationError(f'Unknown export group: {selection.group}')
            valid_items = {item.id for item in group.items}
            valid_dimensions = {dimension.id for dimension in group.dimensions}
            unknown_items = set(selection.items) - valid_items
            unknown_dimensions = set(selection.dimensions) - valid_dimensions
            if unknown_items or unknown_dimensions:
                raise ExportValidationError('Export selection contains stale or unknown fields')
            if group.id != 'citation' and selection.items and not selection.dimensions:
                raise ExportValidationError(f'{group.id} requires at least one dimension')
            selected[group.id] = (set(selection.items), set(selection.dimensions))

        fields: list[OutputField] = []
        for group in schema.groups:
            item_ids, dimensions = selected.get(group.id, (set(), set()))
            for item in group.items:
                if item.id not in item_ids:
                    continue
                if group.id == 'citation':
                    registry = next(row for row in CITATION_FIELDS if row[0] == item.id)
                    # build_schema proved one alias exists; resolve again from current metadata below.
                    fields.append(OutputField(registry[3], registry[2][0]))
                    continue
                available = set(item.available_dimensions or [])
                key = item.id.split('.', 1)[1]
                applicable = dimensions & available
                if not applicable:
                    raise ExportValidationError(f'Requested data is unavailable for {item.id}')
                for dimension in [d.id for d in group.dimensions if d.id in applicable]:
                    fields.extend(self._dimension_fields(group.id, item.label, key, dimension))
        if not fields:
            raise ExportValidationError('At least one output field must be selected')
        return fields

    def _dimension_fields(self, group: str, label: str, key: str, dimension: str) -> list[OutputField]:
        if group in ('l1', 'l2'):
            source = 'human' if dimension == 'human_answer' else 'llm'
            prop = {'human_answer': 'selected', 'ai_answer': 'selected', 'ai_explanation': 'explanation',
                    'confidence': 'confidence', 'evidence': 'evidence_sentences'}[dimension]
            suffix = {'human_answer': 'Human answer', 'ai_answer': 'AI answer',
                      'ai_explanation': 'AI explanation', 'confidence': 'Confidence', 'evidence': 'Evidence'}[dimension]
            return [OutputField(f'{group.upper()} | {label} | {suffix}', f'{source}_{key}', prop)]
        source = 'human' if dimension == 'human_value' else 'llm'
        column = f'{source}_param_{key}'
        if dimension in ('human_value', 'ai_value'):
            prefix = 'Human' if source == 'human' else 'AI'
            return [OutputField(f'Parameter | {label} | {prefix} found', column, 'found'),
                    OutputField(f'Parameter | {label} | {prefix} value', column, 'value')]
        prop = 'explanation' if dimension == 'ai_explanation' else 'evidence_sentences'
        suffix = 'AI explanation' if dimension == 'ai_explanation' else 'Evidence'
        return [OutputField(f'Parameter | {label} | {suffix}', column, prop)]

    def export_csv(
        self, table_name: str, sr: dict[str, Any], request: CitationExportRequest,
    ) -> bytes:
        columns = cits_dp_service.get_table_columns(table_name)
        actual = {str(c['column_name']).casefold(): str(c['column_name']) for c in columns}
        schema = self.build_schema(sr, table_name, columns)
        fields = self.resolve(schema, request)
        # Resolve citation aliases and preserve only identifiers proven by current metadata.
        resolved = []
        for field in fields:
            physical = actual.get(field.column.casefold())
            if not physical and field.property is None:
                registry = next(row for row in CITATION_FIELDS if row[3] == field.header)
                physical = next((actual.get(alias.casefold()) for alias in registry[2] if actual.get(alias.casefold())), None)
            if not physical or _denied(physical):
                raise ExportValidationError(f'Export field is no longer available: {field.header}')
            resolved.append(OutputField(field.header, physical, field.property))

        scope = request.row_scope
        if scope.kind in ('l1_included', 'l2_included'):
            cits_dp_service.backfill_human_decisions((sr or {}).get('criteria_parsed') or {}, table_name)
        rows = cits_dp_service.fetch_export_rows(
            table_name, sorted({field.column for field in resolved}), scope.kind,
            scope.citation_ids,
        )
        if scope.kind == 'citation_ids':
            requested_ids = set(scope.citation_ids or [])
            returned_ids = {int(row['id']) for row in rows}
            if requested_ids != returned_ids:
                raise ExportValidationError('One or more citation IDs do not belong to this review')

        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([field.header for field in resolved])
        for row in rows:
            writer.writerow([self._cell(row.get(field.column), field.property) for field in resolved])
        return output.getvalue().encode('utf-8-sig')

    def _cell(self, value: Any, prop: str | None) -> str:
        if prop is not None:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    value = {}
            value = value.get(prop) if isinstance(value, dict) else None
        if value is None:
            text = ''
        elif isinstance(value, (list, dict)):
            text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        else:
            text = str(value)
        # OWASP-compatible spreadsheet formula injection mitigation.
        if re.match(r'^[\t\r ]*[=+\-@]', text):
            text = "'" + text
        return text


citation_export_service = CitationExportService()