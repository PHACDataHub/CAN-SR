from __future__ import annotations

from typing import Optional

import psycopg
import psycopg_pool
import procrastinate
from procrastinate import exceptions as procrastinate_exceptions
from procrastinate.psycopg_connector import PsycopgConnector

from ..core.config import settings
from ..services.postgres_auth import postgres_server


# ---------------------------------------------------------------------------
# Azure token-refreshing pool
# ---------------------------------------------------------------------------

def _make_azure_pool() -> psycopg_pool.AsyncConnectionPool:
    """Return an AsyncConnectionPool whose connections always carry a fresh
    Entra ID token as their password.

    We subclass psycopg.AsyncConnection and override connect() so that every
    time the pool opens a new physical connection it calls
    postgres_server._refresh_azure_token() first. That method is cached and
    only hits Azure AD when the token is within 60 s of expiry.
    """
    class AzureTokenConnection(psycopg.AsyncConnection):
        @classmethod
        async def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
            kwargs["password"] = postgres_server._refresh_azure_token()
            return await super().connect(conninfo, **kwargs)

    return psycopg_pool.AsyncConnectionPool(
        conninfo=postgres_server.build_conninfo(include_password=False),
        connection_class=AzureTokenConnection,
        open=False,  # caller must await pool.open() before use
    )


# ---------------------------------------------------------------------------
# Connector factory
# ---------------------------------------------------------------------------

class _AzurePsycopgConnector(PsycopgConnector):
    """PsycopgConnector that creates a token-refreshing pool for Azure.

    PsycopgConnector.open_async() accepts an already-constructed pool via its
    `pool` kwarg, so we build the pool here and hand it off — the rest of the
    connector (execute_query_*, etc.) is unchanged.
    """

    async def open_async(self, pool=None, **kwargs) -> None:  # type: ignore[override]
        if pool is None:
            pool = _make_azure_pool()
            await pool.open()
        await super().open_async(pool=pool, **kwargs)


def _build_connector() -> PsycopgConnector:
    if settings.POSTGRES_MODE == "azure":
        return _AzurePsycopgConnector()
    return PsycopgConnector(conninfo=postgres_server.build_conninfo())


# ---------------------------------------------------------------------------
# Module-level app singleton
# ---------------------------------------------------------------------------

PROCRASTINATE_APP = procrastinate.App(connector=_build_connector())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def jobs_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_PROCRASTINATE", False))


def workers_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_PROCRASTINATE_WORKER", False))


def worker_concurrency() -> int:
    try:
        return max(1, int(getattr(settings, "PROCRASTINATE_WORKER_CONCURRENCY", 1) or 1))
    except Exception:
        return 1


async def ensure_procrastinate_schema() -> None:
    """Create procrastinate internal tables.

    Notes:
    - Procrastinate 3.2.x ships a `schema.sql` that is *not* idempotent
      (`CREATE TYPE ...` without `IF NOT EXISTS`). If the schema was created
      previously, re-applying it raises `DuplicateObject`.
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

    opened_here = False
    try:
        _ = PROCRASTINATE_APP.connector.pool
    except procrastinate_exceptions.AppNotOpen:
        await PROCRASTINATE_APP.open_async()
        opened_here = True

    try:
        if await _schema_installed():
            return

        try:
            await PROCRASTINATE_APP.schema_manager.apply_schema_async()
        except procrastinate_exceptions.ConnectorException as e:
            cause: BaseException | None = e.__cause__
            if isinstance(cause, (psycopg.errors.DuplicateObject, psycopg.errors.DuplicateTable, psycopg.errors.DuplicateFunction)):
                if await _schema_installed():
                    return
            raise
    finally:
        if opened_here:
            await PROCRASTINATE_APP.close_async()


async def clear_pending_jobs(*, queues: Optional[list[str]] = None) -> int:
    """Best-effort cleanup of leftover Procrastinate jobs.

    Intended for development environments where you frequently restart the API.
    Controlled by an env flag in main.py.

    Returns the number of rows deleted from procrastinate_jobs.
    """

    qs = queues or ["default"]
    opened_here = False
    try:
        _ = PROCRASTINATE_APP.connector.pool
    except procrastinate_exceptions.AppNotOpen:
        await PROCRASTINATE_APP.open_async()
        opened_here = True

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
            await PROCRASTINATE_APP.close_async()


async def cancel_enqueued_jobs_for_run_all(job_id: str, *, queues: Optional[list[str]] = None) -> int:
    """Best-effort: delete enqueued (todo) Procrastinate jobs for a given run-all job_id.

    Returns number of deleted procrastinate_jobs rows.
    """

    qs = queues or ["default"]
    opened_here = False
    try:
        _ = PROCRASTINATE_APP.connector.pool
    except procrastinate_exceptions.AppNotOpen:
        await PROCRASTINATE_APP.open_async()
        opened_here = True

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
            await PROCRASTINATE_APP.close_async()


async def run_worker_once(*, queues: Optional[list[str]] = None) -> None:
    """Run a worker loop. Intended to be launched as a background task."""

    qs = queues or ["default"]
    await PROCRASTINATE_APP.run_worker_async(
        queues=qs,
        concurrency=worker_concurrency(),
    )
