from __future__ import annotations

import unittest

from api.criteria.context import format_citation_context
from api.criteria.context import format_item_context
from api.criteria.context import format_title_abstract_context
from api.criteria.context import match_answer_label
from api.criteria.context import resolve_citation_fields
from api.criteria.context import resolve_existing_human_value
from api.screen.router import _parse_selected_from_human_payload


class CriteriaContextTests(unittest.TestCase):
    def test_title_abstract_format_uses_configured_headers(self) -> None:
        row = {
            'Paper title': 'Configured title',
            'Paper abstract': 'Configured abstract', 'Year': 2025,
        }
        result = format_title_abstract_context(
            row, {
                'title': 'Paper title', 'abstract': 'Paper abstract', 'l1_include': ['Paper title', 'Year'],
            },
        )
        self.assertEqual(
            result, 'Title: Configured title\nAbstract: Configured abstract\nOther fields: Year: 2025',
        )
        self.assertIn('Year: 2025', result)

    def test_answer_matching_is_formatting_only_and_preserves_raw_value(self) -> None:
        matched = match_answer_label(
            '  Yes   ', [{'id': 'yes', 'label': 'Yes'}],
        )
        self.assertEqual(matched['status'], 'matched')
        self.assertEqual(matched['raw'], '  Yes   ')
        self.assertEqual(
            match_answer_label(
                'Probably', [{'id': 'yes', 'label': 'Yes'}],
            )['status'], 'unmatched',
        )
        self.assertEqual(
            match_answer_label(
                '   ', [{'id': 'yes', 'label': 'Yes'}],
            )['status'], 'blank',
        )

    def test_parameter_mapping_is_authoritative_when_valid(self) -> None:
        result = resolve_existing_human_value(
            {'reviewer value': '42'},
            {'answer_column': 'reviewer value', 'name': 'Rate', 'type': 'text'},
        )
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['value'], '42')

    def test_item_context_keeps_option_context_separate(self) -> None:
        result = format_item_context({
            'question': 'Eligible?', 'context': 'Item guidance',
            'answers': [{'label': 'Yes', 'context': 'Yes guidance'}],
        })
        self.assertIn('Context: Item guidance', result)
        self.assertIn('- Yes: Yes guidance', result)

    def test_metrics_ignore_legacy_llm_autofilled_human_values(self) -> None:
        self.assertIsNone(
            _parse_selected_from_human_payload(
                {'selected': 'Yes', 'source': 'llm', 'autofilled': True},
            ),
        )
        self.assertIsNone(
            _parse_selected_from_human_payload(
                {'selected': 'Yes', 'source': 'csv_upload', 'autofilled': True},
            ),
        )
        self.assertEqual(
            _parse_selected_from_human_payload(
                {
                    'selected': 'No', 'human': True,
                    'reviewer': 'reviewer@example.com',
                },
            ),
            'No',
        )


if __name__ == '__main__':
    unittest.main()


def test_only_configured_additional_citation_fields_are_included_in_screening_context():
    row = {
        'title': 'Retrospective title',
        'abstract': 'Retrospective abstract',
        'journal': 'Journal of Open Studies',
        'publication_type': 'Retrospective study',
        'year': '2024',
    }
    result = format_title_abstract_context(
        row, {
            'title': 'Title', 'abstract': 'Abstract',
            'l1_include': ['publication_type'],
        },
    )
    assert 'Title: Retrospective title' in result
    assert 'Abstract: Retrospective abstract' in result
    assert 'publication_type: Retrospective study' in result
    assert 'journal:' not in result
    assert 'year:' not in result


# Regression: configuring an additional citation field (e.g. "type") must not
# drop the title and abstract from the screening prompt. The individual re-run
# endpoints used to rebuild the context from citation_fields.l1_include alone,
# which silently screened the citation on that one field.
CONFERENCE_ROW = {
    'id': 7,
    'title': 'Measles outbreak in Ontario',
    'abstract': 'We studied 1200 cases of measles.',
    'type': 'Conference Proceedings',
}


def test_additional_citation_field_does_not_replace_title_and_abstract():
    result = format_citation_context(
        CONFERENCE_ROW, {
            'citation_fields': {
                'title': 'Title', 'abstract': 'Abstract',
                'l1_include': ['type'],
            },
        },
    )
    assert 'Title: Measles outbreak in Ontario' in result
    assert 'Abstract: We studied 1200 cases of measles.' in result
    assert 'type: Conference Proceedings' in result


def test_legacy_include_list_still_gets_title_and_abstract():
    result = format_citation_context(
        CONFERENCE_ROW, {'l1': {'include': ['type']}},
    )
    assert 'Title: Measles outbreak in Ontario' in result
    assert 'Abstract: We studied 1200 cases of measles.' in result
    assert 'type: Conference Proceedings' in result


def test_criteria_without_citation_fields_fall_back_to_canonical_headers():
    result = format_citation_context(CONFERENCE_ROW, {})
    assert 'Title: Measles outbreak in Ontario' in result
    assert 'Abstract: We studied 1200 cases of measles.' in result
    assert 'Other fields: (none configured)' in result


def test_resolve_citation_fields_keeps_explicitly_configured_sources():
    fields = resolve_citation_fields({
        'citation_fields': {
            'title': 'Article Title', 'abstract': 'Summary',
            'l1_include': ['type', ''], 'doi': 'DOI',
        },
    })
    assert fields['title'] == 'Article Title'
    assert fields['abstract'] == 'Summary'
    assert fields['l1_include'] == ['type']
    assert fields['doi'] == 'DOI'
