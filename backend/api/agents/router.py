"""
Main agents router - centralized routing for all agent endpoints
"""

from fastapi import APIRouter

from .agentic_search.router import router as agentic_search_router

# Main agents router
agents_router = APIRouter()

# Include all agent-specific routers
agents_router.include_router(
    agentic_search_router, prefix="/agentic_search", tags=["Agentic Search"]
)
