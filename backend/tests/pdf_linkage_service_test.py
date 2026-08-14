from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from urllib.parse import quote

import httpx
from api.services.fulltext_attachment_service import validate_pdf
from api.services.pdf_linkage_service import _candidate
from api.services.pdf_linkage_service import _download
from api.services.pdf_linkage_service import _is_public_url
from api.services.pdf_linkage_service import _request_with_retry
from api.services.pdf_linkage_service import normalize_doi
from api.services.pdf_linkage_service import OA_API_BASE_URL


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


class PdfLinkageNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_open_access_dois_are_resolved_and_downloaded_over_network(self):
        """Live integration test; run with network access and do not mock the OA path."""
        if os.getenv('CAN_SR_SKIP_NETWORK_TESTS') == '1':
            self.skipTest(
                'network tests disabled by CAN_SR_SKIP_NETWORK_TESTS',
            )

        dois = [
            '10.1371/journal.pone.0000001', '10.1371/journal.pone.0000002',
            '10.1371/journal.pone.0000003', '10.1371/journal.pone.0000004',
            '10.1371/journal.pone.0000005', '10.1371/journal.pone.0000006',
            '10.1371/journal.pone.0000007', '10.1371/journal.pone.0000008',
            '10.1371/journal.pone.0000009', '10.1371/journal.pone.0000010',
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15)) as client:
            for doi in dois:
                try:
                    response = await _request_with_retry(
                        client, f'{OA_API_BASE_URL}?doi={quote(doi, safe="")}',
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    self.skipTest(
                        f'network unavailable for live OA test: {exc}',
                    )
                payload = response.json()
                candidate = _candidate(payload)
                self.assertTrue(
                    candidate, f'No OA PDF URL returned for {doi}: {payload!r}',
                )
                pdf, final_url = await _download(client, candidate)
                self.assertTrue(
                    pdf.lstrip().startswith(
                        b'%PDF',
                    ), f'{doi} did not return a PDF',
                )
                self.assertTrue(final_url.startswith(('http://', 'https://')))


if __name__ == '__main__':
    unittest.main()
