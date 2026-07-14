"""Conservative DOI recovery from NCBI PubMed metadata.

An NCBI API key is optional.  Requests are globally paced at NCBI's published
unauthenticated/authenticated rates and title-search results are accepted only
when citation metadata identifies one unambiguous record.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

EUTILS_BASE_URL = os.getenv(
    'PUBMED_EUTILS_BASE_URL',
    'https://eutils.ncbi.nlm.nih.gov/entrez/eutils',
).rstrip('/')
ENTREZ_EMAIL = (os.getenv('ENTREZ_EMAIL') or '').strip()
ENTREZ_API_KEY = (os.getenv('ENTREZ_API_KEY') or '').strip()
_RATE_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


@dataclass(frozen=True)
class PubMedArticle:
    pmid: str
    doi: str | None
    title: str
    year: str | None
    authors: tuple[str, ...]


def _normalized_text(value: object) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def _year(value: object) -> str | None:
    match = re.search(r'\b(?:18|19|20)\d{2}\b', str(value or ''))
    return match.group(0) if match else None


def _citation_authors(row: dict[str, Any]) -> set[str]:
    value = row.get('authors') or row.get('author') or ''
    if isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = re.split(r'[;,|]', str(value))
    return {
        token
        for part in parts
        if (token := _normalized_text(part).split(' ')[-1] if _normalized_text(part) else '')
    }


def _parse_articles(xml: str) -> list[PubMedArticle]:
    root = ET.fromstring(xml)
    results: list[PubMedArticle] = []
    for record in root.findall('.//PubmedArticle'):
        pmid = ''.join(record.findtext('.//MedlineCitation/PMID', default='').split())
        title_node = record.find('.//MedlineCitation/Article/ArticleTitle')
        title = ''.join(title_node.itertext()) if title_node is not None else ''
        doi = None
        for node in record.findall('.//PubmedData/ArticleIdList/ArticleId'):
            if str(node.attrib.get('IdType', '')).lower() == 'doi' and node.text:
                doi = node.text.strip()
                break
        if not doi:
            for node in record.findall('.//MedlineCitation/Article/ELocationID'):
                if str(node.attrib.get('EIdType', '')).lower() == 'doi' and node.text:
                    doi = node.text.strip()
                    break
        year = (
            record.findtext('.//MedlineCitation/Article/Journal/JournalIssue/PubDate/Year')
            or _year(record.findtext('.//MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate'))
            or _year(record.findtext('.//PubmedData/History/PubMedPubDate/Year'))
        )
        authors: list[str] = []
        for author in record.findall('.//MedlineCitation/Article/AuthorList/Author'):
            name = author.findtext('LastName') or author.findtext('CollectiveName')
            if name:
                authors.append(name.strip())
        if pmid:
            results.append(PubMedArticle(pmid, doi, title, str(year) if year else None, tuple(authors)))
    return results


def _select_title_match(row: dict[str, Any], articles: list[PubMedArticle]) -> PubMedArticle | None:
    title = _normalized_text(row.get('title'))
    if not title:
        return None
    expected_year = _year(row.get('year') or row.get('publication_year') or row.get('date'))
    expected_authors = _citation_authors(row)
    # An exact title alone is not enough to attach a document automatically.
    if not expected_year and not expected_authors:
        return None
    matches: list[PubMedArticle] = []
    for article in articles:
        if not article.doi or _normalized_text(article.title) != title:
            continue
        if expected_year and article.year != expected_year:
            continue
        article_authors = {_normalized_text(name).split(' ')[-1] for name in article.authors}
        if expected_authors and not expected_authors.intersection(article_authors):
            continue
        matches.append(article)
    return matches[0] if len(matches) == 1 else None


async def _pace_request() -> None:
    global _LAST_REQUEST_AT
    interval = 0.11 if ENTREZ_API_KEY else 0.34
    async with _RATE_LOCK:
        delay = interval - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        _LAST_REQUEST_AT = time.monotonic()


def _common_params() -> dict[str, str]:
    params = {'tool': 'CAN-SR'}
    if ENTREZ_EMAIL:
        params['email'] = ENTREZ_EMAIL
    if ENTREZ_API_KEY:
        params['api_key'] = ENTREZ_API_KEY
    return params


async def _get(client: httpx.AsyncClient, endpoint: str, params: dict[str, str]) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        await _pace_request()
        try:
            response = await client.get(
                f'{EUTILS_BASE_URL}/{endpoint}',
                params={**_common_params(), **params},
            )
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f'retryable status {response.status_code}',
                request=response.request,
                response=response,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
        if attempt < 2:
            await asyncio.sleep(0.25 * (2 ** attempt))
    assert last_error is not None
    raise last_error


async def resolve_doi_from_pubmed(
    row: dict[str, Any], *, client: httpx.AsyncClient | None = None,
) -> str | None:
    """Resolve a DOI by exact PMID, then by an unambiguous verified title match."""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5))
    try:
        raw_pmid = str(row.get('pmid') or '').strip()
        pmid_match = re.fullmatch(r'(?i)(?:PMID\s*:\s*)?(\d+)', raw_pmid)
        pmid = pmid_match.group(1) if pmid_match else ''
        if pmid:
            response = await _get(client, 'efetch.fcgi', {
                'db': 'pubmed', 'id': pmid, 'retmode': 'xml',
            })
            articles = _parse_articles(response.text)
            exact = next((item for item in articles if item.pmid == pmid and item.doi), None)
            return exact.doi if exact else None

        title = str(row.get('title') or '').strip()
        if not title:
            return None
        search = await _get(client, 'esearch.fcgi', {
            'db': 'pubmed', 'term': f'"{title}"[Title]', 'retmode': 'json', 'retmax': '5',
        })
        ids = [str(item) for item in search.json().get('esearchresult', {}).get('idlist', [])]
        if not ids:
            return None
        fetched = await _get(client, 'efetch.fcgi', {
            'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml',
        })
        match = _select_title_match(row, _parse_articles(fetched.text))
        return match.doi if match else None
    except (httpx.HTTPError, ET.ParseError, ValueError, KeyError):
        return None
    finally:
        if owns_client:
            await client.aclose()