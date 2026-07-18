import csv
import io

import pytest
from pydantic import ValidationError

from api.citations.export_models import CitationExportRequest
from api.services.citation_export_service import ExportValidationError
from api.services.citation_export_service import citation_export_service
from api.services.cit_db_service import cits_dp_service


def _columns(*names):
    return [{'column_name': name, 'data_type': 'text', 'udt_name': 'text'} for name in names]


def _sr():
    return {
        'criteria_parsed': {
            'l1': {'questions': ['Current question?']},
            'l2': {'questions': ['Current full text question?']},
            'parameters': {
                'categories': ['Outcomes'],
                'possible_parameters': [['Attack rate']],
            },
        },
    }


def test_schema_is_current_config_allowlist_and_excludes_sensitive_columns():
    schema = citation_export_service.build_schema(
        _sr(), 'unused', _columns(
            'id', 'title', 'fulltext_url', 'prompt',
            'human_current_question', 'llm_current_question',
            'human_stale_old_question', 'human_param_attack_rate',
        ),
    )
    citation = schema.groups[0]
    assert [item.id for item in citation.items] == ['citation.id', 'citation.title']
    l1 = schema.groups[1]
    assert [item.id for item in l1.items] == ['l1.current_question']
    assert l1.items[0].available_dimensions == [
        'human_answer', 'ai_answer', 'ai_explanation', 'confidence', 'evidence',
    ]
    assert all('stale' not in item.id for group in schema.groups for item in group.items)


def test_collision_in_current_questions_fails_closed():
    sr = {'criteria_parsed': {'l1': {'questions': ['A!' * 40, 'A?' * 40]}}}
    with pytest.raises(ExportValidationError, match='duplicate key'):
        citation_export_service.build_schema(sr, 'unused', _columns('id'))


def test_unknown_or_unavailable_selection_is_rejected():
    schema = citation_export_service.build_schema(_sr(), 'unused', _columns('id', 'title'))
    request = CitationExportRequest(selections=[{
        'group': 'l1', 'items': ['l1.current_question'], 'dimensions': ['human_answer'],
    }])
    with pytest.raises(ExportValidationError, match='unavailable'):
        citation_export_service.resolve(schema, request)

    stale = CitationExportRequest(selections=[{
        'group': 'citation', 'items': ['citation.stale'],
    }])
    with pytest.raises(ExportValidationError, match='stale or unknown'):
        citation_export_service.resolve(schema, stale)


def test_parameter_label_collision_fails_closed():
    sr = {'criteria_parsed': {'parameters': {
        'categories': ['A', 'B'],
        'possible_parameters': [['Attack rate'], ['Attack rate']],
    }}}
    with pytest.raises(ExportValidationError, match='duplicate key'):
        citation_export_service.build_schema(sr, 'unused', _columns('id'))


@pytest.mark.parametrize('payload', [
    {'row_scope': {'kind': 'citation_ids'}, 'selections': [{'group': 'citation', 'items': ['citation.id']}]},
    {'row_scope': {'kind': 'all', 'citation_ids': [1]}, 'selections': [{'group': 'citation', 'items': ['citation.id']}]},
    {'row_scope': {'kind': 'citation_ids', 'citation_ids': list(range(501))}, 'selections': [{'group': 'citation', 'items': ['citation.id']}]},
])
def test_invalid_row_scope_contract_is_rejected(payload):
    with pytest.raises(ValidationError):
        CitationExportRequest.model_validate(payload)


def test_duplicate_group_and_empty_output_are_rejected():
    schema = citation_export_service.build_schema(_sr(), 'unused', _columns('id'))
    duplicate = CitationExportRequest(selections=[
        {'group': 'citation', 'items': ['citation.id']},
        {'group': 'citation', 'items': ['citation.id']},
    ])
    with pytest.raises(ExportValidationError, match='Duplicate selection group'):
        citation_export_service.resolve(schema, duplicate)
    empty = CitationExportRequest(selections=[{'group': 'citation', 'items': []}])
    with pytest.raises(ExportValidationError, match='At least one output field'):
        citation_export_service.resolve(schema, empty)


def test_parameter_dimensions_expand_in_stable_order():
    schema = citation_export_service.build_schema(
        _sr(), 'unused', _columns('id', 'human_param_attack_rate', 'llm_param_attack_rate'),
    )
    request = CitationExportRequest(selections=[{
        'group': 'parameters', 'items': ['parameters.attack_rate'],
        'dimensions': ['evidence', 'human_value', 'ai_value'],
    }])
    fields = citation_export_service.resolve(schema, request)
    assert [field.header for field in fields] == [
        'Parameter | Attack rate | Human found',
        'Parameter | Attack rate | Human value',
        'Parameter | Attack rate | AI found',
        'Parameter | Attack rate | AI value',
        'Parameter | Attack rate | Evidence',
    ]


def test_select_all_dimensions_uses_each_items_available_intersection():
    schema = citation_export_service.build_schema(
        _sr(), 'unused', _columns('id', 'human_current_question', 'llm_current_full_text_question'),
    )
    request = CitationExportRequest(selections=[
        {
            'group': 'l1',
            'items': ['l1.current_question'],
            'dimensions': ['human_answer', 'ai_answer', 'ai_explanation', 'confidence', 'evidence'],
        },
        {
            'group': 'l2',
            'items': ['l2.current_full_text_question'],
            'dimensions': ['human_answer', 'ai_answer', 'ai_explanation', 'confidence', 'evidence'],
        },
    ])
    fields = citation_export_service.resolve(schema, request)
    assert [field.header for field in fields] == [
        'L1 | Current question? | Human answer',
        'L2 | Current full text question? | AI answer',
        'L2 | Current full text question? | AI explanation',
        'L2 | Current full text question? | Confidence',
        'L2 | Current full text question? | Evidence',
    ]


def test_csv_is_ordered_normalized_and_formula_safe(monkeypatch):
    columns = _columns('id', 'title', 'human_current_question')
    monkeypatch.setattr(cits_dp_service, 'get_table_columns', lambda _table: columns)
    monkeypatch.setattr(
        cits_dp_service, 'fetch_export_rows',
        lambda *_args, **_kwargs: [{
            'id': 1, 'title': '=HYPERLINK("bad")',
            'human_current_question': {'selected': 'Include, yes'},
        }],
    )
    request = CitationExportRequest(selections=[
        {'group': 'citation', 'items': ['citation.title']},
        {'group': 'l1', 'items': ['l1.current_question'], 'dimensions': ['human_answer']},
    ])
    body = citation_export_service.export_csv('citations', _sr(), request).decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0] == ['Title', 'L1 | Current question? | Human answer']
    assert rows[1] == ['\'=HYPERLINK("bad")', 'Include, yes']


def test_citation_id_scope_must_be_entirely_owned(monkeypatch):
    monkeypatch.setattr(cits_dp_service, 'get_table_columns', lambda _table: _columns('id'))
    monkeypatch.setattr(
        cits_dp_service, 'fetch_export_rows',
        lambda *_args, **_kwargs: [{'id': 1}],
    )
    request = CitationExportRequest(
        row_scope={'kind': 'citation_ids', 'citation_ids': [1, 2]},
        selections=[{'group': 'citation', 'items': ['citation.id']}],
    )
    with pytest.raises(ExportValidationError, match='do not belong'):
        citation_export_service.export_csv('citations', _sr(), request)


@pytest.mark.parametrize('scope', ['l1_included', 'l2_included'])
def test_included_scopes_backfill_and_forward_scope(monkeypatch, scope):
    calls = []
    monkeypatch.setattr(cits_dp_service, 'get_table_columns', lambda _table: _columns('id'))
    monkeypatch.setattr(cits_dp_service, 'backfill_human_decisions', lambda *args: calls.append(('backfill', args)))
    monkeypatch.setattr(
        cits_dp_service, 'fetch_export_rows',
        lambda table, columns, kind, ids: calls.append(('fetch', table, columns, kind, ids)) or [],
    )
    request = CitationExportRequest(
        row_scope={'kind': scope},
        selections=[{'group': 'citation', 'items': ['citation.id']}],
    )
    citation_export_service.export_csv('citations', _sr(), request)
    assert calls[0][0] == 'backfill'
    assert calls[1] == ('fetch', 'citations', ['id'], scope, None)