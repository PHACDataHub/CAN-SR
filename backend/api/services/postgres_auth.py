"""
PostgreSQL authentication helper using Azure Entra ID (DefaultAzureCredential).

This module provides a centralized way to connect to Azure Database for PostgreSQL
using Entra ID authentication, with fallback to connection string for local development.
"""

from typing import Optional
import logging
import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

# Azure PostgreSQL OAuth scope
POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
_current_pgsql_token = None
_pgsql_token_expiration = None

def _ensure_psycopg2():
    """Ensure psycopg2 is available."""
    try:
        import psycopg2
        import psycopg2.extras  # noqa: F401
        return psycopg2
    except ImportError:
        raise RuntimeError("psycopg2 is not installed on the server environment")

def get_postgres_token() -> str:
    """
    Get an access token for Azure Database for PostgreSQL using DefaultAzureCredential.
    
    Returns:
        Access token string to use as password for PostgreSQL connection.
    """
    from azure.identity import DefaultAzureCredential
    global _current_pgsql_token, _pgsql_token_expiration
    
    credential = DefaultAzureCredential()
    current_epoch_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    if not _current_pgsql_token or current_epoch_time >= _pgsql_token_expiration:
        token = credential.get_token(POSTGRES_SCOPE)
        _current_pgsql_token = token.token
        _pgsql_token_expiration = token.expires_on - 60  # Refresh 1 minute before expiry
    return _current_pgsql_token
    
def connect_with_entra_id(
    host: str,
    database: str,
    user: str,
    port: int = 5432,
    sslmode: str = "require",
):
    """
    Connect to Azure Database for PostgreSQL using Entra ID authentication.
    
    Args:
        host: PostgreSQL server hostname (e.g., myserver.postgres.database.azure.com)
        database: Database name
        user: Entra ID user (e.g., user@tenant.onmicrosoft.com or managed identity client ID)
        port: PostgreSQL port (default 5432)
        sslmode: SSL mode (default "require")
    
    Returns:
        psycopg2 connection object
    """
    psycopg2 = _ensure_psycopg2()
    
    # Get access token from Entra ID
    access_token = get_postgres_token()
    
    conn = psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=access_token,
        port=port,
        sslmode=sslmode,
    )
    
    return conn


def connect_postgres(db_conn_str: Optional[str] = None):
    """
    Connect to PostgreSQL using Entra ID authentication (preferred) or connection string (fallback).
    
    If POSTGRES_HOST, POSTGRES_DATABASE, and POSTGRES_USER are configured, uses Entra ID authentication.
    Otherwise, falls back to the provided connection string (for local development).
    
    Args:
        db_conn_str: Optional connection string (used as fallback for local dev)
    
    Returns:
        psycopg2 connection object
    """
    from ..core.config import settings
    
    # Prefer Entra ID authentication if configured
    if settings.POSTGRES_HOST and settings.POSTGRES_DATABASE and settings.POSTGRES_USER:
        logger.debug("Connecting to PostgreSQL using Entra ID authentication")
        return connect_with_entra_id(
            host=settings.POSTGRES_HOST,
            database=settings.POSTGRES_DATABASE,
            user=settings.POSTGRES_USER,
            port=settings.POSTGRES_PORT,
            sslmode=settings.POSTGRES_SSL_MODE,
        )
    
    # Fallback to connection string (local development)
    if db_conn_str:
        logger.debug("Connecting to PostgreSQL using connection string")
        psycopg2 = _ensure_psycopg2()
        return psycopg2.connect(db_conn_str)
    
    # Check for POSTGRES_URI as final fallback
    if settings.POSTGRES_URI:
        logger.debug("Connecting to PostgreSQL using POSTGRES_URI")
        psycopg2 = _ensure_psycopg2()
        return psycopg2.connect(settings.POSTGRES_URI)
    
    raise RuntimeError(
        "PostgreSQL not configured. Set POSTGRES_HOST, POSTGRES_DATABASE, and POSTGRES_USER "
        "for Entra ID auth, or POSTGRES_URI for local development."
    )


def pgsql_entra_auth_configured():
    from ..core.config import settings
    has_entra_config = settings.POSTGRES_HOST and settings.POSTGRES_DATABASE and settings.POSTGRES_USER
    return has_entra_config