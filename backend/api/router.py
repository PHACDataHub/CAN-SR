from fastapi import APIRouter

from .auth.router import router as auth_router
from .files.router import router as files_router
from .agents.router import agents_router
from .sr.router import router as sr_router
from .citations.router import router as citation_router
from .screen.router import router as screen_router
from .extract.router import router as extract_router
from .database_search.router import router as database_search_router

api_router = APIRouter()

# Authentication API
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])

# File management API
api_router.include_router(files_router, prefix="/files", tags=["Files"])

# Agents API (for future CAN-SR agent implementations)
api_router.include_router(agents_router, prefix="/agents", tags=["AI Agents"])

# Systematic Review API
api_router.include_router(sr_router, prefix="/sr", tags=["SR Setup"])

# Citations API
api_router.include_router(citation_router, prefix="/cite", tags=["Citations"])

# Screening API
api_router.include_router(screen_router, prefix="/screen", tags=["Screening"])

# Extraction API
api_router.include_router(extract_router, prefix="/extract", tags=["Extraction"])

# Database Search API
api_router.include_router(database_search_router, prefix="/database_search", tags=["Database Search"])
