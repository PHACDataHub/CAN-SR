from __future__ import annotations

import unittest

from api.services.citation_field_service import build_citation_field_contract


class CitationFieldServiceTests(unittest.TestCase):
    def test_preserves_order_filters_runtime_columns_and_reports_unavailable(self):
        result = build_citation_field_contract(
            {
                'criteria': {
                    'citation_fields': {
                        'l1_include': ['Title', 'Missing'], 'doi': 'DOI',
                    },
                },
            },
            [{'column_name': name, 'data_type': 'text'} for name in [
                'id', 'Title', 'Abstract', 'DOI', 'human_answer', 'fulltext_url',
            ]],
        )
        self.assertEqual(
            result['fields'], [
                {'name': 'Title', 'data_type': 'text'},
                {'name': 'Abstract', 'data_type': 'text'},
                {'name': 'DOI', 'data_type': 'text'},
            ],
        )
        self.assertEqual(result['unavailable_configured_fields'], ['Missing'])

    def test_supports_review_without_upload(self):
        self.assertEqual(build_citation_field_contract({}, [])['fields'], [])
