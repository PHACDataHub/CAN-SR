import os
import uvicorn
import logging
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
from api.services.user_db import user_db_service


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Startup event - initialize CAN-SR systematic review database"""
    from fastapi.concurrency import run_in_threadpool
    import asyncio
    
    # Reduce Azure SDK HTTP logging noise (especially during polling endpoints).
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

    print("🚀 Starting CAN-SR Backend...", flush=True)
    print("📚 Initializing systematic review database...", flush=True)
    # Ensure systematic review table exists in PostgreSQL
    try:
        # POSTGRES_URI is deprecated; the DB connection is handled by postgres_server
        # using POSTGRES_MODE/POSTGRES_* settings.
        await run_in_threadpool(srdb_service.ensure_table_exists)
        print("✓ Systematic review table initialized", flush=True)
    except Exception as e:
        print(f"⚠️ Failed to ensure SR table exists: {e}", flush=True)

    if user_db_service:
        await user_db_service.ensure_table_exists()
        print("✓ Users table initialized", flush=True)

    # Procrastinate schema + run-all job tables
    try:
        from api.jobs.procrastinate_app import (
            jobs_enabled,
            ensure_procrastinate_schema,
            workers_enabled,
            run_worker_once,
            clear_pending_jobs,
        )
        from api.jobs.run_all_repo import run_all_repo

        if jobs_enabled():
            print("🧰 Ensuring background job tables...", flush=True)
            # Keep Procrastinate open for the whole API lifespan so request handlers
            # can enqueue jobs.
            from api.jobs.procrastinate_app import PROCRASTINATE_APP
            await PROCRASTINATE_APP.open_async()
            await ensure_procrastinate_schema()
            await run_in_threadpool(run_all_repo.ensure_tables)
            print("✓ Job tables initialized", flush=True)

            # Optional dev cleanup: clear out leftover queued/doing tasks from previous runs.
            # Controlled by PROCRASTINATE_CLEAR_ON_START (defaults to true if unset).
            if getattr(settings, "PROCRASTINATE_CLEAR_ON_START", True):
                try:
                    cleared = await clear_pending_jobs(queues=["default"])
                    print(f"🧹 Cleared {cleared} pending Procrastinate jobs", flush=True)
                except Exception as e:
                    print(f"⚠️ Failed to clear pending Procrastinate jobs: {e}", flush=True)

            if workers_enabled():
                # Run a worker loop inside the API process (dev/quick deploy).
                # For production, run a separate worker service.
                print("👷 Starting embedded Procrastinate worker...", flush=True)
                asyncio.create_task(run_worker_once(queues=["default"]))
    except Exception as e:
        print(f"⚠️ Background jobs not started: {e}", flush=True)
    print("🎯 CAN-SR Backend ready!", flush=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event - close background resources."""
    try:
        from api.jobs.procrastinate_app import jobs_enabled, PROCRASTINATE_APP

        if jobs_enabled():
            await PROCRASTINATE_APP.close_async()
    except Exception:
        pass

    


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
        "azure_openai_mode": settings.AZURE_OPENAI_MODE,
        "postgres_mode": settings.POSTGRES_MODE,
        "storage_mode": settings.STORAGE_MODE,
        "azure_openai_configured": azure_openai_client.is_configured(),
        "default_chat_model": settings.DEFAULT_CHAT_MODEL,
        "available_models": azure_openai_client.get_available_models(),
        "available_deployments": azure_openai_client.get_available_deployments(),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
