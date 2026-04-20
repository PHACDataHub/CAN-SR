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
from ..services.storage import storage_service
from io import BytesIO

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
    
    if not storage_service:
        raise HTTPException(status_code=500, detail="Storage not configured")

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

    archive_path = (
        f"{settings.STORAGE_CONTAINER_NAME}/"
        f"citation-data/bronze-data/{database}/archive/{blob_name}"
    )

    try:
        await save_df(archive_path, content)
        logging.info(f"Uploaded blob '{blob_name}' to container '{settings.STORAGE_CONTAINER_NAME}'")
    except AzureError as e:
        logging.error(f"Azure Blob Storage error: {e.message if hasattr(e, 'message') else str(e)}")
        raise HTTPException(status_code=500, detail="Failed to write to Azure Blob")
    except Exception as ex:
        logging.error(f"Unexpected error: {str(ex)}")
        raise HTTPException(status_code=500, detail="Unexpected error while writing to blob")

    all_path = (
        f"{settings.STORAGE_CONTAINER_NAME}/"
        f"citation-data/bronze-data/{database}/{database}-all-citations.csv"
    )

    try:
        bytes_data, _ = await storage_service.get_bytes_by_path(all_path)
        all_citations_df = pd.read_csv(BytesIO(bytes_data))
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

    await save_df(all_path, new_all_citations)
    
    silver_path = (
        f"{settings.STORAGE_CONTAINER_NAME}/"
        f"citation-data/silver-data/silver-citation-data.csv"
    )
    combined_df = await load_all_database_searches()
    combined_df = normalize_ids(combined_df)
    await save_df(silver_path, combined_df)

    return {"message": f"{database} collection completed", "new_citations_count": len(new_citations)}

@router.get("/{sr_id}/combine")
async def combine_sources(sr_id: str):
    combined_df = await load_all_database_searches()

    if combined_df.empty:
        return {"message": "No data found, perform search first"}

    combined_df = normalize_ids(combined_df)

    silver_path = (
        f"{settings.STORAGE_CONTAINER_NAME}/"
        f"citation-data/silver-data/silver-citation-data.csv"
    )

    await save_df(silver_path, combined_df)

    return {
        "total citations": len(combined_df)
    }
    