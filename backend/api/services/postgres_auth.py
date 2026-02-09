"""
PostgreSQL authentication helper using Azure Entra ID (DefaultAzureCredential).

This module provides a centralized way to connect to Azure Database for PostgreSQL
using Entra ID authentication, with fallback to connection string for local development.
"""

from typing import Optional

import psycopg2
from ..core.config import settings
import logging
import datetime
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


class PostgresServer:
    """Manages a persistent PostgreSQL connection with automatic Azure token refresh."""

    _AZURE_POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
    _TOKEN_REFRESH_BUFFER_SECONDS = 60

    def __init__(self):
        self._verify_config()
        self._credential = DefaultAzureCredential() if settings.AZURE_DB else None
        self._token: Optional[str] = None
        self._token_expiration: int = 0
        self._conn = None

    @property
    def conn(self):
        """Return an open connection, reconnecting only when necessary."""
        if self._conn is None or self._conn.closed:
            print("local database")
            self._conn = self._connect()
        elif settings.AZURE_DB and self._is_token_expired():
            logger.info("Azure token expired — reconnecting to PostgreSQL")
            print("cloud database")
            self.close()
            self._conn = self._connect()
        print(self._conn)
        return self._conn

    def close(self):
        """Safely close the current connection (idempotent)."""
        if self._conn and not self._conn.closed:
            try:
                self._conn.close()
            except Exception:
                logger.warning("Failed to close PostgreSQL connection", exc_info=True)
        self._conn = None

    @staticmethod
    def _verify_config():
        """Validate that all required PostgreSQL settings are present."""
        required = [settings.POSTGRES_HOST, settings.POSTGRES_DATABASE, settings.POSTGRES_USER]
        if not all(required):
            raise RuntimeError("POSTGRES_HOST, POSTGRES_DATABASE, and POSTGRES_USER are required")
        if not settings.AZURE_DB and not settings.POSTGRES_PASSWORD:
            raise RuntimeError("POSTGRES_PASSWORD is required when AZURE_DB is False")

    def _is_token_expired(self) -> bool:
        """Check whether the cached Azure token needs refreshing."""
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        return not self._token or now >= self._token_expiration

    def _refresh_azure_token(self) -> str:
        """Return a valid Azure token, fetching a new one only if expired."""
        if self._is_token_expired():
            logger.info("Fetching fresh Azure PostgreSQL token")
            token = self._credential.get_token(self._AZURE_POSTGRES_SCOPE)
            self._token = token.token
            self._token_expiration = token.expires_on - self._TOKEN_REFRESH_BUFFER_SECONDS
        return self._token

    def _build_connect_kwargs(self) -> dict:
        """Assemble psycopg2.connect() keyword arguments from settings."""
        kwargs = {
            "host": settings.POSTGRES_HOST,
            "database": settings.POSTGRES_DATABASE,
            "user": settings.POSTGRES_USER,
            "port": settings.POSTGRES_PORT,
        }
        if settings.POSTGRES_SSL_MODE:
            kwargs["sslmode"] = settings.POSTGRES_SSL_MODE
        if settings.AZURE_DB:
            kwargs["password"] = self._refresh_azure_token()
        elif settings.POSTGRES_PASSWORD:
            kwargs["password"] = settings.POSTGRES_PASSWORD
        return kwargs

    def _connect(self):
        """Create a new psycopg2 connection."""
        return psycopg2.connect(**self._build_connect_kwargs())

    def __repr__(self) -> str:
        status = "open" if self._conn and not self._conn.closed else "closed"
        return (
            f"<PostgresServer host={settings.POSTGRES_HOST} "
            f"db={settings.POSTGRES_DATABASE} conn={status}>"
        )

postgres_server = PostgresServer()