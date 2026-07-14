from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from api.services.pubmed_doi_service import (
    PubMedArticle,
    _common_params,
    _select_title_match,
    resolve_doi_from_pubmed,
)


XML = '''<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>Effects of Vaccination: A Study</ArticleTitle>
<AuthorList><Author><LastName>Smith</LastName></Author></AuthorList>
<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
</Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>'''


class PubMedDoiSelectionTests(unittest.TestCase):
    def test_title_match_requires_corroborating_metadata(self):
        article = PubMedArticle('123', '10.1/x', 'Same Title', '2024', ('Smith',))
        self.assertIsNone(_select_title_match({'title': 'Same Title'}, [article]))
        self.assertEqual(
            _select_title_match(
                {'title': 'Same Title', 'year': '2024', 'authors': 'Jane Smith'},
                [article],
            ),
            article,
        )

    def test_ambiguous_or_mismatched_results_are_rejected(self):
        article = PubMedArticle('1', '10.1/a', 'Same Title', '2024', ('Smith',))
        other = PubMedArticle('2', '10.1/b', 'Same Title', '2024', ('Smith',))
        row = {'title': 'Same Title', 'year': '2024', 'authors': 'Smith'}
        self.assertIsNone(_select_title_match(row, [article, other]))
        self.assertIsNone(_select_title_match({**row, 'year': '2023'}, [article]))

    def test_api_key_is_optional(self):
        with patch('api.services.pubmed_doi_service.ENTREZ_EMAIL', 'team@example.test'), patch(
            'api.services.pubmed_doi_service.ENTREZ_API_KEY', '',
        ):
            self.assertEqual(
                _common_params(), {'tool': 'CAN-SR', 'email': 'team@example.test'},
            )


class PubMedDoiResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.common_params = patch(
            'api.services.pubmed_doi_service._common_params',
            return_value={'tool': 'CAN-SR'},
        )
        self.common_params.start()

    def tearDown(self):
        self.common_params.stop()

    async def test_exact_pmid_resolves_doi(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params['id'], '123')
            return httpx.Response(200, text=XML, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch(
                'api.services.pubmed_doi_service._pace_request',
                new=AsyncMock(),
            ):
                self.assertEqual(
                    await resolve_doi_from_pubmed({'pmid': 'PMID: 123'}, client=client),
                    '10.1000/example',
                )

    async def test_invalid_pmid_does_not_get_digits_coerced(self):
        client = AsyncMock()
        self.assertIsNone(
            await resolve_doi_from_pubmed({'pmid': 'not-123', 'title': ''}, client=client),
        )
        client.get.assert_not_awaited()

    async def test_verified_title_search_resolves_doi(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith('/esearch.fcgi'):
                return httpx.Response(
                    200, json={'esearchresult': {'idlist': ['123']}}, request=request,
                )
            return httpx.Response(200, text=XML, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch(
                'api.services.pubmed_doi_service._pace_request',
                new=AsyncMock(),
            ):
                doi = await resolve_doi_from_pubmed(
                    {
                        'title': 'Effects of Vaccination: A Study',
                        'authors': 'Jane Smith',
                        'year': '2024',
                    },
                    client=client,
                )
        self.assertEqual(doi, '10.1000/example')

    async def test_provider_failure_returns_none(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch(
                'api.services.pubmed_doi_service._pace_request', new=AsyncMock(),
            ), patch('api.services.pubmed_doi_service.asyncio.sleep', new=AsyncMock()):
                self.assertIsNone(
                    await resolve_doi_from_pubmed({'pmid': '123'}, client=client),
                )


if __name__ == '__main__':
    unittest.main()