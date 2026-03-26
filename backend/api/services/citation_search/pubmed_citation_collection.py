import os
from Bio import Entrez
import pandas as pd
import requests
import logging
import string
import time

# from unidecode import unidecode
from cleantext import clean
from datetime import datetime
from ...core.config import settings

# PubMed API configuration
ENTREZ_EMAIL = settings.ENTREZ_EMAIL
ENTREZ_API_KEY = settings.ENTREZ_API_KEY
# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("grep-exp-pubmed-citations")


class PubMedCitationCollector:
    def __init__(self):
        self.citations = []

    def extract_citation_data(self, paper):
        """Extract citation metadata from a PubMed article"""
        try:
            # Basic information
            title = paper["MedlineCitation"]["Article"].get("ArticleTitle", "")
            if title:
                title = clean(title.rstrip("."), lower=False, fix_unicode=True)

            pmid = str(paper["MedlineCitation"]["PMID"])

            # Authors
            authors = []
            if "AuthorList" in paper["MedlineCitation"]["Article"]:
                for author in paper["MedlineCitation"]["Article"]["AuthorList"]:
                    last_name = author.get("LastName", "")
                    fore_name = author.get("ForeName", "")
                    full_name = " ".join(filter(None, [fore_name, last_name]))
                    if full_name:
                        authors.append(full_name)

            # Keywords
            keywords = []
            if (
                "KeywordList" in paper["MedlineCitation"]
                and paper["MedlineCitation"]["KeywordList"]
            ):
                keywords = [
                    str(kw) for kw in paper["MedlineCitation"]["KeywordList"][0]
                ]

            # DOI
            doi = None
            for e_location in paper["MedlineCitation"]["Article"].get(
                "ELocationID", []
            ):
                if e_location.attributes["EIdType"] == "doi":
                    doi = str(e_location)
                    break

            # If no DOI found in article, try CrossRef
            if doi is None:
                doi = self.find_doi_crossref(title)

            # Date
            article_date = paper["MedlineCitation"]["Article"].get("ArticleDate", [])
            date = None
            if article_date:
                date = f"{article_date[0]['Year']}/{article_date[0]['Month']}/{article_date[0]['Day']}"

            # Abstract
            abstract_texts = (
                paper["MedlineCitation"]["Article"]
                .get("Abstract", {})
                .get("AbstractText", [])
            )
            abstract = " ".join([str(text) for text in abstract_texts])

            # Journal info
            journal_info = paper["MedlineCitation"]["Article"]["Journal"]

            # Publication Type
            pt = [
                str(pt)
                for pt in paper["MedlineCitation"]["Article"]["PublicationTypeList"]
            ]

            # Compile citation data
            citation_data = {
                "source": "PubMed",
                "id": pmid,
                "title": title,
                "authors": ", ".join(authors),
                "abstract": abstract,
                "keywords": ", ".join(keywords),
                "doi": doi,
                "pmid": pmid,
                "journal": journal_info["Title"],
                "issn": "".join(journal_info.get("ISSN", [])),
                "publication_types": ", ".join(pt),
                "date": date,
                "year": paper["MedlineCitation"]["Article"]["Journal"]["JournalIssue"][
                    "PubDate"
                ].get("Year"),
                "volume": journal_info["JournalIssue"].get("Volume"),
                "issue": journal_info["JournalIssue"].get("Issue"),
                "language": ", ".join(
                    paper["MedlineCitation"]["Article"].get("Language", [])
                ),
                "pdf_attempted": False,
                "pdf_success": False,
                "pdf_url": None,
                "pdf_error": None,
            }

            return citation_data

        except Exception as e:
            logger.error(f"Error extracting citation data: {e}")
            return None

    def collect_citations(
        self, search_term, mindate=None, maxdate=None, max_articles=1000
    ):
        """Main method to collect citations from PubMed"""

        Entrez.email = ENTREZ_EMAIL
        Entrez.api_key = ENTREZ_API_KEY

        logger.info(f"Starting PubMed citation collection")
        logger.info(f"Search term: {search_term[:100]}...")
        if mindate and maxdate:
            logger.info(f"Date range: {mindate} to {maxdate}")
        elif mindate:
            logger.info(f"Date range: {mindate} to present")
        elif maxdate:
            logger.info(f"Date range: earliest to {maxdate}")
        else:
            logger.info("No date range specified")

        search_params = {
            "db": "pubmed",
            "sort": "pub_date",
            "retmode": "xml",
            "retmax": max_articles,
            "term": search_term,
        }

        if mindate:
            search_params["mindate"] = mindate
        if maxdate:
            search_params["maxdate"] = maxdate

        try:
            handle = Entrez.esearch(**search_params)
            pmid_list = Entrez.read(handle)
            pmid_list = pmid_list.get("IdList", [])
        except Exception as e:
            logger.error(f"Error searching PubMed: {e}")
            pmid_list = []

        # Search PubMed
        # pmid_list = search_pubmed(search_term, mindate, maxdate, max_articles)

        if not pmid_list:
            logger.warning("No PMIDs found")
            return []

        total_pmids = len(pmid_list)
        logger.info(f"Found {total_pmids} PMIDs")

        # Limit to max_articles
        if max_articles and total_pmids > max_articles:
            logger.info(f"Limiting to {max_articles} articles")
            pmid_list = pmid_list[:max_articles]

        # Fetch article details
        logger.info(f"Fetching details for {len(pmid_list)} articles")
        papers = self.fetch_details_batch(pmid_list)

        # Extract citation data
        self.citations = []
        for i, paper in enumerate(papers):
            try:
                #   logger.info(f"Processing article {i+1}/{len(papers)}")
                citation_data = self.extract_citation_data(paper)
                if citation_data:
                    self.citations.append(citation_data)

            except Exception as e:
                logger.error(f"Error processing paper {i}: {e}")
                continue

        logger.info(f"Successfully collected {len(self.citations)} citations")
        return self.citations

    def find_doi_crossref(self, title):
        """Find DOI using CrossRef API"""
        if not title:
            return None

        url = "https://api.crossref.org/works"
        params = {"query.title": title, "rows": 1}

        try:
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                items = data["message"]["items"]

                if items:
                    first_item = items[0]
                    result_title = first_item["title"][0]

                    if self.clean_title(result_title) == self.clean_title(title):
                        return first_item["DOI"]

            return None
        except Exception as e:
            logger.warning(f"Error finding DOI for title: {e}")
            return None

    def fetch_details_batch(self, id_list, batch_size=50):
        """Fetch details for PubMed IDs in batches"""
        if not id_list:
            return []

        Entrez.email = ENTREZ_EMAIL
        Entrez.api_key = ENTREZ_API_KEY

        all_results = []
        print(id_list)
        print(f"Number of IDs: {len(id_list)}")

        # id_list = list(id_list)

        for i in range(0, len(id_list), batch_size):
            batch_ids = id_list[i : i + batch_size]
            ids = ",".join(batch_ids)

            try:
                handle = Entrez.efetch(db="pubmed", retmode="xml", id=ids)
                results = Entrez.read(handle)

                if "PubmedArticle" in results:
                    all_results.extend(results["PubmedArticle"])

                # Add delay to be nice to API
                if i + batch_size < len(id_list):
                    time.sleep(1)

            except Exception as e:
                logger.error(
                    f"Error fetching details for batch {i//batch_size + 1}: {e}"
                )
                continue

        return all_results

    def clean_title(self, title):
        """Clean and normalize a title"""
        if not title:
            return ""
        title = title.lower()
        title = title.translate(str.maketrans("", "", string.punctuation))
        return title
