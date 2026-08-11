from __future__ import annotations

import unittest

from api.criteria.context import format_item_context
from api.criteria.context import format_title_abstract_context
from api.criteria.context import match_answer_label
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
        self.assertEqual(
            _parse_selected_from_human_payload(
                {'selected': 'Yes', 'source': 'csv_upload', 'autofilled': True},
            ),
            'Yes',
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
