from __future__ import annotations

import unittest

from api.services.citation_field_service import build_citation_field_contract


class CitationFieldServiceTests(unittest.TestCase):
    def test_preserves_order_filters_runtime_columns_and_suggests_doi(self):
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
            [field['name'] for field in result['fields']], [
                'Title', 'Abstract', 'DOI',
            ],
        )
        self.assertEqual(result['doi_suggestions'], ['DOI'])
        self.assertEqual(result['unavailable_configured_fields'], ['Missing'])

    def test_supports_likely_doi_header_and_review_without_upload(self):
        result = build_citation_field_contract(
            {}, [{'column_name': 'Digital Object Identifier', 'data_type': 'text'}],
        )
        self.assertEqual(
            result['doi_suggestions'], [
                'Digital Object Identifier',
            ],
        )
        self.assertEqual(build_citation_field_contract({}, [])['fields'], [])
