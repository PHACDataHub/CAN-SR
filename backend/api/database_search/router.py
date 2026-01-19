import requests
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from ..core.security import get_current_active_user
from ..core.config import settings

router = APIRouter()

class SearchRequest(BaseModel):
    database: str = Field(..., description="database selected for search")
    search_term: Optional[str] = Field("", description="search string for database search")


@router.post("/{sr_id}/search")
async def database_search(
    sr_id: str, payload: SearchRequest, current_user: Dict[str, Any] = Depends(get_current_active_user), 
):
    databricks_instance = settings.DATABRICKS_INSTANCE
    databricks_token = settings.DATABRICKS_TOKEN
    job_ids = {
        "EuropePMC": settings.JOB_ID_EUROPEPMC,
        "Pubmed": settings.JOB_ID_PUBMED,
        "Scopus": settings.JOB_ID_SCOPUS
    }
    job_id = job_ids.get(payload.database)

    url = f"{databricks_instance}/api/2.1/jobs/run-now"
    headers = {
        "Authorization": f"Bearer {databricks_token}",
        "Content-Type": "application/json"
    }
    data = {
        "job_id": job_id,
        "notebook_params": {
            "search_term": payload.search_term
        }
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()