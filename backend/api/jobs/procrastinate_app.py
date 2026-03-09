from __future__ import annotations

import asyncio
import os
from typing import Optional

import psycopg
import psycopg_pool
import procrastinate
from procrastinate import exceptions as procrastinate_exceptions
from procrastinate.psycopg_connector import PsycopgConnector

from ..core.config import settings
from ..services.postgres_auth import postgres_server


# ---------------------------------------------------------------------------
# Connection pool factory
# ---------------------------------------------------------------------------

def _conninfo_without_password() -> str:
    """Build a psycopg3 conninfo string from the individual POSTGRES_* settings.

    Password is intentionally omitted — each mode injects credentials differently:
    - docker/local: passed via pool ``kwargs`` so special characters are safe
    - azure:        injected per-connection by ``_AzureEntraConnection.connect()``
    """
    prof = settings.postgres_profile()
    mapping = [
        ("host",    prof.get("host")),
        ("dbname",  prof.get("database")),
        ("user",    prof.get("user")),
        ("port",    prof.get("port")),
        ("sslmode", prof.get("sslmode")),
    ]
    return " ".join(f"{k}={v}" for k, v in mapping if v)


async def _configure_connection(conn: psycopg.AsyncConnection) -> None:
    """Set autocommit on every connection checked out of the pool.

    Procrastinate requires autocommit=True; without it queries that use
    advisory locks or LISTEN/NOTIFY fail with a generic 'Database error.'
    """
    await conn.set_autocommit(True)


async def _build_pool() -> psycopg_pool.AsyncConnectionPool:
    """Create and open an AsyncConnectionPool for the current POSTGRES_MODE."""
    mode = settings.POSTGRES_MODE.lower().strip()
    conninfo = _conninfo_without_password()

    if mode == "azure":
        # psycopg_pool bakes conninfo at construction time — there is no
        # password-callback API.  Overriding connection_class.connect() is the
        # only hook where we can inject a just-in-time credential.
        #
        # postgres_server.refresh_azure_token() shares one DefaultAzureCredential
        # and one token cache across the whole process.
        # The sync call runs in a thread pool executor to avoid blocking the
        # event loop during the rare (~every 55 min) AAD refresh round-trip.
        class _AzureEntraConnection(psycopg.AsyncConnection):
            @classmethod
            async def connect(  # type: ignore[override]
                cls, conninfo: str = "", **kwargs
            ) -> "_AzureEntraConnection":
                token = await asyncio.get_running_loop().run_in_executor(
                    None, postgres_server.refresh_azure_token
                )
                return await super().connect(conninfo, password=token, **kwargs)

        pool = psycopg_pool.AsyncConnectionPool(
            conninfo=conninfo,
            connection_class=_AzureEntraConnection,
            open=False,
            configure=_configure_connection,
            max_lifetime=3300,  # 55 min — recycle before ~60 min Entra token window
            min_size=1,
            max_size=10,
        )
    else:
        # docker / local — plain password from POSTGRES_PASSWORD
        password = settings.postgres_profile().get("password")
        if not password:
            raise RuntimeError(
                f"POSTGRES_PASSWORD is required for POSTGRES_MODE={mode}"
            )
        pool = psycopg_pool.AsyncConnectionPool(
            conninfo=conninfo,
            # kwargs so special characters in the password are handled safely.
            kwargs={"password": password},
            open=False,
            configure=_configure_connection,
            min_size=1,
            max_size=10,
        )

    await pool.open()
    return pool


# ---------------------------------------------------------------------------
# App singleton
# ---------------------------------------------------------------------------

# Created without connection args so nothing is evaluated at import time.
# Always open/close through open_procrastinate_app() / close_procrastinate_app().
PROCRASTINATE_APP = procrastinate.App(connector=PsycopgConnector())

# Tracks the pool we created so close_procrastinate_app() can tear it down.
# When an external pool is passed to open_async(), procrastinate marks it
# "externally managed" and skips closing it in close_async().
_pool: Optional[psycopg_pool.AsyncConnectionPool] = None


async def open_procrastinate_app() -> None:
    """Open PROCRASTINATE_APP with the correct pool for the current POSTGRES_MODE."""
    global _pool
    # procrastinate 3.2.x handles JSON/autocommit configuration internally at
    # the cursor level (_wrap_json); no external configure callback is needed.
    _pool = await _build_pool()
    await PROCRASTINATE_APP.open_async(pool=_pool)


async def close_procrastinate_app() -> None:
    """Close PROCRASTINATE_APP and its connection pool."""
    global _pool
    try:
        await PROCRASTINATE_APP.close_async()
    except Exception:
        pass
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def jobs_enabled() -> bool:
    return os.getenv("ENABLE_PROCRASTINATE", "false").lower().strip() == "true"


def workers_enabled() -> bool:
    return os.getenv("ENABLE_PROCRASTINATE_WORKER", "false").lower().strip() == "true"


def worker_concurrency() -> int:
    try:
        return max(1, int(os.getenv("PROCRASTINATE_WORKER_CONCURRENCY", "1")))
    except Exception:
        return 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _ensure_app_open() -> bool:
    """Open the app if not already open. Returns True if opened here."""
    try:
        _ = PROCRASTINATE_APP.connector.pool
        return False
    except procrastinate_exceptions.AppNotOpen:
        await open_procrastinate_app()
        return True


# ---------------------------------------------------------------------------
# Schema / maintenance
# ---------------------------------------------------------------------------

async def ensure_procrastinate_schema() -> None:
    """Create procrastinate internal tables.

    Notes:
    - Procrastinate 3.2.x ships a schema.sql that is *not* idempotent
      (CREATE TYPE ... without IF NOT EXISTS). If the schema was created
      previously, re-applying it raises DuplicateObject.
    - To keep the API startup stable, we treat "already installed" as success.
    """

    async def _schema_installed() -> bool:
        try:
            row = await PROCRASTINATE_APP.connector.execute_query_one_async(
                """
                SELECT
                  to_regclass('procrastinate_jobs') IS NOT NULL AS jobs_table,
                  EXISTS(SELECT 1 FROM pg_type WHERE typname = 'procrastinate_job_status') AS status_enum
                """  # noqa: S608
            )
            return bool(row.get("jobs_table") and row.get("status_enum"))
        except Exception:
            return False

    opened_here = await _ensure_app_open()

    try:
        if await _schema_installed():
            return

        try:
            await PROCRASTINATE_APP.schema_manager.apply_schema_async()
        except procrastinate_exceptions.ConnectorException as e:
            cause: BaseException | None = e.__cause__
            if isinstance(
                cause,
                (
                    psycopg.errors.DuplicateObject,
                    psycopg.errors.DuplicateTable,
                    psycopg.errors.DuplicateFunction,
                ),
            ):
                if await _schema_installed():
                    return
            raise
    finally:
        if opened_here:
            await close_procrastinate_app()


async def clear_pending_jobs(*, queues: Optional[list[str]] = None) -> int:
    """Best-effort cleanup of leftover Procrastinate jobs.

    Intended for development environments where you frequently restart the API.
    Returns the number of rows deleted from procrastinate_jobs.
    """
    qs = queues or ["default"]
    opened_here = await _ensure_app_open()

    try:
        rows = await PROCRASTINATE_APP.connector.execute_query_all_async(
            """
            DELETE FROM procrastinate_jobs
            WHERE status IN ('todo', 'doing')
              AND queue_name = ANY(%(queues)s)
            RETURNING 1
            """,  # noqa: S608
            queues=qs,
        )
        return len(rows or [])
    finally:
        if opened_here:
            await close_procrastinate_app()


async def cancel_enqueued_jobs_for_run_all(
    job_id: str, *, queues: Optional[list[str]] = None
) -> int:
    """Best-effort: delete enqueued (todo) Procrastinate jobs for a given run-all job_id.

    Jobs already in `doing` cannot be safely removed here and will stop cooperatively
    once they next check run_all_repo.is_canceled(job_id).

    Returns number of deleted procrastinate_jobs rows.
    """
    qs = queues or ["default"]
    opened_here = await _ensure_app_open()

    try:
        rows = await PROCRASTINATE_APP.connector.execute_query_all_async(
            """
            DELETE FROM procrastinate_jobs
            WHERE status = 'todo'
              AND queue_name = ANY(%(queues)s)
              AND (args ->> 'job_id') = %(job_id)s
            RETURNING 1
            """,  # noqa: S608
            queues=qs,
            job_id=str(job_id),
        )
        return len(rows or [])
    finally:
        if opened_here:
            await close_procrastinate_app()


async def run_worker_once(*, queues: Optional[list[str]] = None) -> None:
    """Run a worker loop. Intended to be launched as a background task.

    If you run this inside the API process, set concurrency low.
    """
    qs = queues or ["default"]
    await PROCRASTINATE_APP.run_worker_async(
        queues=qs,
        concurrency=worker_concurrency(),
    )
