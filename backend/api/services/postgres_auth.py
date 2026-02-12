"""backend.api.services.postgres_auth

PostgreSQL connection helper supporting three runtime modes.

Configuration model:
* POSTGRES_MODE selects behavior: docker | local | azure
* Connection settings are provided via a single set of env vars:
  - POSTGRES_HOST
  - POSTGRES_DATABASE
  - POSTGRES_USER
  - POSTGRES_PASSWORD

Auth behavior:
* docker/local: password auth (POSTGRES_PASSWORD required)
* azure: Entra token auth via DefaultAzureCredential (password ignored)

Behavior:
* Only try the configured POSTGRES_MODE (no fallback).

Notes:
* POSTGRES_URI is deprecated and intentionally not used.
"""

import os
from typing import Optional, Dict, Any

import psycopg2
from ..core.config import settings
import logging
import datetime

try:
    from azure.identity import DefaultAzureCredential
except Exception:  # pragma: no cover
    DefaultAzureCredential = None  # type: ignore

logger = logging.getLogger(__name__)


class PostgresServer:
    """Manages a persistent PostgreSQL connection with automatic Azure token refresh."""

    _AZURE_POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
    _TOKEN_REFRESH_BUFFER_SECONDS = 60

    def __init__(self):
        self._verify_config()
        self._credential = DefaultAzureCredential() if self._mode() == "azure" else None
        self._token: Optional[str] = None
        self._token_expiration: int = 0
        self._conn = None

    @property
    def conn(self):
        """Return an open connection, reconnecting only when necessary."""
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
        elif self._mode() == "azure" and self._is_token_expired():
            logger.info("Azure token expired — reconnecting to PostgreSQL")
            self.close()
            self._conn = self._connect()
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
        mode = (settings.POSTGRES_MODE or "").lower().strip()
        if mode not in {"local", "docker", "azure"}:
            raise RuntimeError("POSTGRES_MODE must be one of: local, docker, azure")

        # Validate selected profile minimally; the rest is validated when building kwargs.
        try:
            prof = settings.postgres_profile(mode)
        except Exception as e:
            raise RuntimeError(str(e))

        required = [prof.get("host"), prof.get("database"), prof.get("user")]
        if not all(required):
            raise RuntimeError(f"{mode} profile requires host, database and user")

        if mode in {"docker", "local"} and not prof.get("password"):
            raise RuntimeError(f"{mode} mode requires POSTGRES_PASSWORD")

    def _is_token_expired(self) -> bool:
        """Check whether the cached Azure token needs refreshing."""
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        return not self._token or now >= self._token_expiration

    def _refresh_azure_token(self) -> str:
        """Return a valid Azure token, fetching a new one only if expired."""
        if self._is_token_expired():
            logger.info("Fetching fresh Azure PostgreSQL token")
            if not self._credential:
                raise RuntimeError(
                    "Azure credential is not configured. Ensure POSTGRES_MODE=azure and that "
                    "DefaultAzureCredential can authenticate in this environment."
                )
            token = self._credential.get_token(self._AZURE_POSTGRES_SCOPE)
            self._token = token.token
            self._token_expiration = token.expires_on - self._TOKEN_REFRESH_BUFFER_SECONDS
        return self._token

    @staticmethod
    def _mode() -> str:
        return (settings.POSTGRES_MODE or "docker").lower().strip()

    @staticmethod
    def _has_local_fallback() -> bool:
        return False

    def _candidate_kwargs(self, mode: str) -> Dict[str, Any]:
        """Build connect kwargs for a given mode based on POSTGRES_* env vars."""
        prof = settings.postgres_profile(mode)

        kwargs: Dict[str, Any] = {
            "host": prof.get("host"),
            "database": prof.get("database"),
            "user": prof.get("user"),
            "port": int(prof.get("port") or 5432),
            # Fail fast so connection errors surface quickly
            "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "3")),
        }

        sslmode = prof.get("sslmode")
        if sslmode:
            kwargs["sslmode"] = sslmode

        if prof.get("mode") == "azure":
            kwargs["password"] = self._refresh_azure_token()
        else:
            if not prof.get("password"):
                raise RuntimeError(f"{mode} profile requires password")
            kwargs["password"] = prof.get("password")

        # Sanity checks
        required = [kwargs.get("host"), kwargs.get("database"), kwargs.get("user"), kwargs.get("port")]
        if not all(required):
            raise RuntimeError(f"Incomplete Postgres config for mode={mode}")

        return kwargs

    def _connect_with_mode(self, mode: str):
        kwargs = self._candidate_kwargs(mode)
        safe_kwargs = {k: ("***" if k == "password" else v) for k, v in kwargs.items()}
        logger.info("Connecting to Postgres (mode=%s) %s", mode, safe_kwargs)
        return psycopg2.connect(**kwargs)

    def _connect(self):
        """Create a new psycopg2 connection."""
        primary_mode = self._mode()
        try:
            return self._connect_with_mode(primary_mode)
        except Exception as e:
            logger.error("Postgres connect failed (mode=%s): %s", primary_mode, e, exc_info=True)
            raise psycopg2.OperationalError(
                f"Could not connect to Postgres for mode={primary_mode}"
            )

    def __repr__(self) -> str:
        status = "open" if self._conn and not self._conn.closed else "closed"
        return (
            f"<PostgresServer mode={settings.POSTGRES_MODE} conn={status}>"
        )

postgres_server = PostgresServer()