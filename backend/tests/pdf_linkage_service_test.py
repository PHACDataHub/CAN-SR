from __future__ import annotations

import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from api.services.fulltext_attachment_service import validate_pdf
from api.services.pdf_linkage_service import _candidate
from api.services.pdf_linkage_service import _is_public_url
from api.services.pdf_linkage_service import link_citation_pdf
from api.services.pdf_linkage_service import normalize_doi


class PdfLinkageServiceTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(normalize_doi('https://doi.org/10.1/ABC'), '10.1/ABC')
        self.assertEqual(normalize_doi('doi:10.2/test'), '10.2/test')

    def test_candidate_supports_nested_provider_payload(self):
        self.assertEqual(
            _candidate(
                {'data': {'best_oa_location': {'url_for_pdf': 'https://x.test/a.pdf'}}},
            ),
            'https://x.test/a.pdf',
        )

    def test_private_and_metadata_destinations_are_rejected(self):
        with patch('api.services.pdf_linkage_service.socket.getaddrinfo') as resolve:
            resolve.return_value = [
                (None, None, None, None, ('169.254.169.254', 80)),
            ]
            self.assertFalse(_is_public_url('http://metadata.test/latest'))

    def test_pdf_validation(self):
        self.assertTrue(validate_pdf(b'%PDF-1.7\nbody'))
        with self.assertRaisesRegex(ValueError, 'invalid_pdf'):
            validate_pdf(b'<html>not pdf</html>')


class PdfLinkageDoiFallbackTests(unittest.IsolatedAsyncioTestCase):
    @patch('api.services.pdf_linkage_service._download', new_callable=AsyncMock)
    @patch('api.services.pdf_linkage_service._request_with_retry', new_callable=AsyncMock)
    @patch('api.services.pdf_linkage_service.attach_fulltext_document', new_callable=AsyncMock)
    @patch('api.services.pdf_linkage_service.resolve_doi_from_pubmed', new_callable=AsyncMock)
    @patch('api.services.pdf_linkage_service.cits_dp_service')
    async def test_recovered_doi_is_saved_and_used_for_oa_lookup(
        self, db, resolve, attach, request, download,
    ):
        db.get_citation_by_id.return_value = {
            'id': 7, 'doi': '', 'pmid': '123', 'fulltext_url': '',
        }
        resolve.return_value = '10.1000/recovered'
        response = MagicMock()
        response.json.return_value = {
            'url_for_pdf': 'https://example.test/paper.pdf',
        }
        request.return_value = response
        download.return_value = (
            b'%PDF-1.7\n', 'https://example.test/paper.pdf',
        )
        attach.return_value = MagicMock(attached=True)

        outcome = await link_citation_pdf(
            citation_id=7, table_name='citations', user_id='user-1',
        )

        self.assertEqual(outcome.status, 'linked')
        db.save_recovered_doi.assert_called_once_with(
            7, '10.1000/recovered', source='pubmed', table_name='citations',
        )
        self.assertIn('doi=10.1000%2Frecovered', request.await_args.args[1])

    @patch('api.services.pdf_linkage_service.resolve_doi_from_pubmed', new_callable=AsyncMock)
    @patch('api.services.pdf_linkage_service.cits_dp_service')
    async def test_unresolved_doi_keeps_manual_upload_fallback(self, db, resolve):
        db.get_citation_by_id.return_value = {
            'id': 7, 'doi': '', 'title': 'Unknown', 'fulltext_url': '',
        }
        resolve.return_value = None

        outcome = await link_citation_pdf(
            citation_id=7, table_name='citations', user_id='user-1',
        )

        self.assertEqual(outcome.reason, 'missing_doi')
        db.update_pdf_linkage_outcome.assert_called_once_with(
            7, status='manual_upload_required', reason='missing_doi',
            table_name='citations',
        )


if __name__ == '__main__':
    unittest.main()
