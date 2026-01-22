import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

from api.router import api_router
from api.core.config import settings
from api.services.sr_db_service import srdb_service


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Startup event - initialize CAN-SR systematic review database"""
    print("🚀 Starting CAN-SR Backend...", flush=True)
    print("📚 Initializing systematic review database...", flush=True)
    # Ensure systematic review collection exists when Mongo is configured.
    # srdb_service.ensure_collection_exists uses motor (async) and is safe to call here.
    try:
        await srdb_service.ensure_collection_exists()
        print("✓ Systematic review collection initialized", flush=True)
    except Exception as e:
        print(f"⚠️ Failed to ensure SR collection exists: {e}", flush=True)
    print("🎯 CAN-SR Backend ready!", flush=True)

    


# Set up CORS
cors_origins = (
    settings.CORS_ORIGINS.split(",")
    if isinstance(settings.CORS_ORIGINS, str)
    else [settings.CORS_ORIGINS]
)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, same_site="lax", https_only=settings.IS_DEPLOYED)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


# Root endpoint
@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# Health check endpoint
@app.get("/health")
async def health_check():
    from api.services.azure_openai_client import azure_openai_client

    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "storage_type": settings.STORAGE_TYPE,
        "azure_storage_configured": bool(settings.AZURE_STORAGE_CONNECTION_STRING),
        "azure_openai_configured": azure_openai_client.is_configured(),
        "default_chat_model": settings.DEFAULT_CHAT_MODEL,
        "available_models": azure_openai_client.get_available_models(),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
