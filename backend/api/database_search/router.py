import requests
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from ..core.security import get_current_active_user
from ..core.config import settings
from ..services.citation_search.pubmed_citation_collection import PubMedCitationCollector
from ..services.citation_search.europePMC_citation_collection import EuropePMCCitationCollector
from ..services.citation_search.scopus_citation_collection import ScopusDataProcessor
from ..services.citation_search.citation_search_helper import * 

import logging
import os
import pandas as pd
from io import StringIO, BytesIO
import azure.functions as func
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient

import datetime



router = APIRouter()

class SearchRequest(BaseModel):
    database: str = Field(..., description="database selected for search")
    search_term: Optional[str] = Field("", description="search string for database search")


@router.post("/{sr_id}/search")
async def database_search(
    sr_id: str, payload: SearchRequest, current_user: Dict[str, Any] = Depends(get_current_active_user), 
):
    
    MAX_ARTICLES = 1000
    MINDATE = None
    MAXDATE = None
    database = payload.database
    SEARCH_TERM = payload.search_term

    if not SEARCH_TERM :
        SEARCH_TERM = '(("epidemiological parameters"[Title/Abstract] OR "incidence"[MeSH Terms]))'
    logging.info(f"{database} search function started at {datetime.datetime.now()}", )

    if database == "Pubmed":
        collector = PubMedCitationCollector()

        try:
            citations = collector.collect_citations(
                search_term=SEARCH_TERM,
                mindate=MINDATE,
                maxdate=MAXDATE,
                max_articles=MAX_ARTICLES
            )
        except Exception as e:
            logging.error(f"Error collecting citations: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to collect citations")

        content = pd.DataFrame(citations)
    elif database == "EuropePMC":
        collector = EuropePMCCitationCollector()

        try: 
            citations = collector.collect_citations(search_term = SEARCH_TERM, max_articles=MAX_ARTICLES)
        except Exception as e:
            logging.error(f"Error collecting citations: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to collect citations")
        content = pd.DataFrame(citations)
    elif database == "Scopus":
        
        
        SCOPUS_API_KEY = settings.SCOPUS_API_KEY or None #currently don't have

        API_URL = settings.SCOPUS_API_URL

        if not SCOPUS_API_KEY or not API_URL:
            logging.error("Missing SCOPUS_API_KEY or SCOPUS_BASE_URL in environment settings.")
            raise HTTPException(status_code=500, detail="Missing SCOPUS_API_KEY or SCOPUS_BASE_URL")

        processor = ScopusDataProcessor(SCOPUS_API_KEY, API_URL)
        processor.consume_api(SEARCH_TERM, delay=15)
        content = pd.DataFrame.from_dict(processor.data)


    blob_name = f"{database}-{datetime.datetime.now().strftime('%Y-%m-%d')}.csv"
    container_name = f"citation-data/bronze-data/{database}/archive"
    try:
        write_df_to_blob(content, blob_name, container_name)
        logging.info(f"Uploaded blob '{blob_name}' to container '{container_name}'")
    except AzureError as e:
        logging.error(f"Azure Blob Storage error: {e.message if hasattr(e, 'message') else str(e)}")
        raise HTTPException(status_code=500, detail="Failed to write to Azure Blob")
    except Exception as ex:
        logging.error(f"Unexpected error: {str(ex)}")
        raise HTTPException(status_code=500, detail="Unexpected error while writing to blob")

    try:
        all_citations_df = read_blob_to_df(f"{database}-all-citations.csv", f"citation-data/bronze-data/{database}")
    except Exception:
        all_citations_df = content.iloc[0:0].copy() 

    new_all_citations = (
        pd.concat([all_citations_df, content], ignore_index=True)
        .drop_duplicates(subset="pmid", keep="first")
    )
    new_citations = content[~content["pmid"].isin(all_citations_df["pmid"])]

    if new_citations.empty:
        logging.info('No new citations on %s', datetime.datetime.now())
        return {"message": "No new citations", "new_count": 0}

    logging.info('New citations found: %s', len(new_citations))

    write_df_to_blob(new_all_citations, f"{database}-all-citations.csv", f"citation-data/bronze-data/{database}")
    write_df_to_blob(new_citations, blob_name, "citation-deduplicate/to-process")

    combined_df = load_all_database_searches()
    combined_df = normalize_ids(combined_df)
    write_df_to_blob( combined_df, f"silver-citation-data.csv", "citation-data/silver-data")

    return {"message": f"{database} collection completed", "new_citations_count": len(new_citations)}

@router.get("/{sr_id}/combine")
async def combine_sources(sr_id: str):
    combined_df = load_all_database_searches()

    if combined_df.empty:
        return {"message": "No data found, perform search first"}

    combined_df = normalize_ids(combined_df)
    write_df_to_blob( combined_df, f"silver-citation-data.csv", "citation-data/silver-data")

    return {
        "total citations": len(combined_df)
    }
    