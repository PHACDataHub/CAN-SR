from __future__ import annotations

import os
from typing import Optional

import procrastinate
from procrastinate import exceptions as procrastinate_exceptions
from procrastinate.psycopg_connector import PsycopgConnector
import psycopg

from ..core.config import settings


def build_postgres_dsn() -> str:
    """Build a DSN for Procrastinate.

    Notes:
    - For now we only support password auth (docker/local). If POSTGRES_MODE=azure,
      we raise so we don't silently run jobs without a working queue.
    - This can be extended later to use Azure token auth by injecting a password
      token similarly to postgres_auth.PostgresServer.
    """

    mode = (settings.POSTGRES_MODE or "").lower().strip()
    prof = settings.postgres_profile(mode)

    if prof.get("mode") == "azure":
        raise RuntimeError(
            "Procrastinate asyncpg DSN for POSTGRES_MODE=azure is not implemented yet. "
            "Run workers with docker/local Postgres first, or extend build_postgres_dsn() to use Entra tokens."
        )

    host = prof.get("host")
    db = prof.get("database")
    user = prof.get("user")
    password = prof.get("password")
    port = int(prof.get("port") or 5432)
    if not (host and db and user and password):
        raise RuntimeError("Missing Postgres config for Procrastinate")

    # psycopg DSN
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


PROCRASTINATE_APP = procrastinate.App(
    # Procrastinate 3.2.x no longer ships an asyncpg connector; use psycopg (v3).
    # PsycopgConnector forwards kwargs to psycopg_pool.AsyncConnectionPool which expects
    # `conninfo` (not `dsn`).
    connector=PsycopgConnector(conninfo=build_postgres_dsn()),
    # Namespace for internal procrastinate tables
    # You can set this later to avoid collisions.
)


def jobs_enabled() -> bool:
    return os.getenv("ENABLE_PROCRASTINATE", "false").lower().strip() == "true"


def workers_enabled() -> bool:
    return os.getenv("ENABLE_PROCRASTINATE_WORKER", "false").lower().strip() == "true"


def worker_concurrency() -> int:
    try:
        return max(1, int(os.getenv("PROCRASTINATE_WORKER_CONCURRENCY", "1")))
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

    # Ensure the app is open. If it was already open, do not close it here;
    # the API process keeps it open for the whole lifespan.
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
            # If schema is already present (possibly created by a previous run),
            # treat duplicate-object errors as success.
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
        # NOTE: status values are stored in the procrastinate_job_status enum.
        # We only delete jobs that haven't started yet.
        # Procrastinate's PsycopgConnector.execute_query_async does not accept a positional
        # params dict; it only accepts keyword arguments.
        # It also returns None, so to report a deleted count we use RETURNING.
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

    This makes Cancel feel more responsive by removing jobs that haven't started yet.
    Jobs already in `doing` cannot be safely removed here and will stop cooperatively
    once they next check `run_all_repo.is_canceled(job_id)`.

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
    """Run a worker loop. Intended to be launched as a background task.

    If you run this inside the API process, set concurrency low.
    """

    qs = queues or ["default"]
    await PROCRASTINATE_APP.run_worker_async(
        queues=qs,
        concurrency=worker_concurrency(),
    )
