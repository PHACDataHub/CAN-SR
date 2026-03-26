import requests
import time
import logging
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("grep-exp-pubmed-citations")


class EuropePMCCitationCollector:
    def __init__(self):
        self.base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        self.citations = []

        # Set up retry-capable session
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def fetch_data(self, search_term, cursor_mark="*"):
        """Fetch data from Europe PMC API with cursor-based pagination"""
        try:
            params = {
                "query": search_term,
                "pageSize": 100,
                "format": "json",
                "cursorMark": cursor_mark,
            }

            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"API Error: {e}")
            logger.error(f"Request URL: {response.url}")
            return {"resultList": {"result": []}, "nextCursorMark": None}
        except Exception as e:
            logger.error(f"Unexpected error in API request: {e}")
            return {"resultList": {"result": []}, "nextCursorMark": None}

    def extract_citation_data(self, entry):
        """Extract citation metadata from a Europe PMC entry"""
        try:
            # Parse year safely
            year = None
            if entry.get("pubYear"):
                try:
                    year = int(entry.get("pubYear"))
                except (ValueError, TypeError):
                    year = None

            # Extract keywords safely
            keywords = []
            keyword_list = entry.get("keywordList")
            if isinstance(keyword_list, dict) and "keyword" in keyword_list:
                keywords = (
                    keyword_list["keyword"]
                    if isinstance(keyword_list["keyword"], list)
                    else [keyword_list["keyword"]]
                )

            # Extract publication types safely
            pub_types = []
            pub_type_list = entry.get("pubTypeList")
            if isinstance(pub_type_list, dict) and "pubType" in pub_type_list:
                pub_types = (
                    pub_type_list["pubType"]
                    if isinstance(pub_type_list["pubType"], list)
                    else [pub_type_list["pubType"]]
                )

            # Extract full text URLs safely
            full_text_urls = []
            full_text_url_list = entry.get("fullTextUrlList")
            if (
                isinstance(full_text_url_list, dict)
                and "fullTextUrl" in full_text_url_list
            ):
                urls = full_text_url_list["fullTextUrl"]
                if isinstance(urls, list):
                    full_text_urls = [
                        url.get("url")
                        for url in urls
                        if isinstance(url, dict) and url.get("url")
                    ]
                elif isinstance(urls, dict):
                    if urls.get("url"):
                        full_text_urls = [urls["url"]]

            citation_data = {
                "source": "Europe PMC",
                "id": entry.get("id"),
                "pmid": entry.get("pmid"),
                "pmcid": entry.get("pmcid"),
                "title": entry.get("title"),
                "authors": (
                    entry.get("authorList", {}).get("author", [])
                    if isinstance(entry.get("authorList"), dict)
                    else []
                ),
                "author_string": entry.get("authorString"),
                "abstract": entry.get("abstractText"),
                "keywords": keywords,
                "doi": entry.get("doi"),
                "journal": entry.get("journalTitle"),
                "issn": entry.get("journalIssn"),
                "volume": entry.get("journalVolume"),
                "issue": entry.get("issue"),
                "pages": entry.get("pageInfo"),
                "publication_types": pub_types,
                "date": entry.get("firstPublicationDate"),
                "year": year,
                "language": entry.get("language"),
                "full_text_urls": full_text_urls,
                "is_open_access": entry.get("isOpenAccess"),
                "has_pdf": entry.get("hasPDF"),
                "pdf_attempted": False,
                "pdf_success": False,
                "pdf_url": None,
                "pdf_error": None,
            }

            return citation_data

        except Exception as e:
            logger.error(
                f"Error extracting citation data from Europe PMC entry {entry.get('id', 'Unknown ID')}: {e}"
            )
            return None

    def collect_citations(self, search_term, max_articles=1000):
        """Main method to collect citations from Europe PMC"""
        logger.info(f"Starting Europe PMC citation collection")
        logger.info(f"Search query: {search_term[:100]}...")

        try:
            cursor_mark = "*"
            total_processed = 0
            next_cursor_mark = None
            self.citations = []

            # Continue until we reach max_articles or no more results
            while cursor_mark != next_cursor_mark and total_processed < max_articles:
                # Fetch batch
                response_data = self.fetch_data(search_term, cursor_mark)
                entries = response_data.get("resultList", {}).get("result", [])

                if not entries:
                    logger.info("No more results found or API error")
                    break

                # Update cursor for next request
                next_cursor_mark = response_data.get("nextCursorMark")

                # Log progress
                batch_size = len(entries)
                logger.info(f"Retrieved batch of {batch_size} articles. Processing...")

                # Process entries
                for i, entry in enumerate(entries):
                    if total_processed >= max_articles:
                        logger.info(
                            f"Reached maximum number of articles ({max_articles})"
                        )
                        break

                    try:
                        article_num = total_processed + i + 1
                        logger.info(
                            f"Processing article {article_num}: {entry.get('title', 'Unknown title')}"
                        )

                        citation_data = self.extract_citation_data(entry)
                        if citation_data:
                            self.citations.append(citation_data)

                    except Exception as e:
                        logger.error(f"Error processing entry: {e}")
                        continue

                # Update for next iteration
                total_processed += len(entries)
                logger.info(f"Processed {total_processed} articles so far")

                # Update cursor for next request
                if next_cursor_mark and next_cursor_mark != cursor_mark:
                    cursor_mark = next_cursor_mark
                    # Delay between batches
                    logger.info(f"Pausing before next batch...")
                    time.sleep(2)
                else:
                    break

            logger.info(
                f"Completed processing. Collected {len(self.citations)} citations."
            )
            return self.citations

        except Exception as e:
            logger.error(f"Unexpected error in citation collection: {e}")
            return []
