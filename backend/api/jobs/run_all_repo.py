from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from ..services.postgres_auth import postgres_server


def _safe_rollback(conn) -> None:
    try:
        if conn:
            conn.rollback()
    except Exception:
        pass


class RunAllRepo:
    """Persist and query run-all job state.

    This is separate from Procrastinate's own internal tables; it's what the UI polls.

    We keep this minimal and synchronous (psycopg2) so it can be used from both
    async routes and background tasks via run_in_threadpool.
    """

    def ensure_tables(self) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS run_all_jobs (
                    id UUID PRIMARY KEY,
                    sr_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    model TEXT,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    done INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    phase TEXT,
                    error TEXT,
                    meta JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    started_at TIMESTAMP WITH TIME ZONE,
                    finished_at TIMESTAMP WITH TIME ZONE
                )
                """
            )

            # Migration safety: older deployments may have allowed multiple active
            # jobs per SR. Creating the partial unique index would fail if such
            # duplicates exist. Before creating the index, we dedupe by keeping
            # the most recent active job per sr_id and canceling older ones.
            cur.execute(
                """
                WITH ranked AS (
                    SELECT id,
                           sr_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY sr_id
                               ORDER BY created_at DESC NULLS LAST
                           ) AS rn
                    FROM run_all_jobs
                    WHERE status IN ('queued', 'running', 'paused')
                )
                UPDATE run_all_jobs j
                SET status = 'canceled',
                    finished_at = COALESCE(j.finished_at, now()),
                    error = COALESCE(j.error, 'Canceled due to duplicate active job')
                FROM ranked r
                WHERE j.id = r.id
                  AND r.rn > 1
                """
            )

            # Enforce: only one active run-all job per SR at a time.
            # Active statuses are queued/running/paused.
            # This is the critical concurrency guard (race-safe across users).
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS run_all_jobs_one_active_per_sr
                ON run_all_jobs (sr_id)
                WHERE status IN ('queued', 'running', 'paused')
                """
            )
            # Store only failures as requested
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS run_all_job_errors (
                    id BIGSERIAL PRIMARY KEY,
                    job_id UUID NOT NULL REFERENCES run_all_jobs(id) ON DELETE CASCADE,
                    citation_id INTEGER,
                    stage TEXT,
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
                """
            )

            # Chunk scheduling table (fairness): store chunk definitions and status.
            # Each run-all job will only enqueue a small number of chunks at a time
            # (prefetch) so multiple run-all jobs can make progress concurrently.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS run_all_job_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    job_id UUID NOT NULL REFERENCES run_all_jobs(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    citation_ids JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'todo',
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    started_at TIMESTAMP WITH TIME ZONE,
                    finished_at TIMESTAMP WITH TIME ZONE,
                    UNIQUE(job_id, chunk_index)
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS run_all_job_chunks_lookup
                ON run_all_job_chunks (job_id, status, chunk_index)
                """
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    # ------------------------------------------------------------------
    # Chunk scheduling (fairness)
    # ------------------------------------------------------------------

    def insert_chunks(self, job_id: str, chunks: list[list[int]]) -> None:
        """Insert chunk rows for a job.

        Idempotent w.r.t. (job_id, chunk_index) uniqueness.
        """
        if not chunks:
            return
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            for idx, ids in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO run_all_job_chunks (job_id, chunk_index, citation_ids, status)
                    VALUES (%s, %s, %s::jsonb, 'todo')
                    ON CONFLICT (job_id, chunk_index) DO NOTHING
                    """,
                    (job_id, int(idx), json.dumps(ids)),
                )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def get_chunk(self, chunk_id: int) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, job_id, chunk_index, citation_ids, status, error, created_at, started_at, finished_at
                FROM run_all_job_chunks
                WHERE id = %s
                """,
                (int(chunk_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            out = {cols[i]: row[i] for i in range(len(cols))}
            if isinstance(out.get("citation_ids"), str):
                try:
                    out["citation_ids"] = json.loads(out["citation_ids"])  # type: ignore
                except Exception:
                    pass
            # normalize
            out["job_id"] = str(out.get("job_id"))
            return out
        except Exception:
            _safe_rollback(conn)
            raise

    def claim_next_todo_chunk(self, job_id: str, *, prefetch: int = 2) -> Optional[int]:
        """Atomically claim the next todo chunk for a job.

        Fairness/throughput tradeoff is controlled by `prefetch`:
        - prefetch=1: at most 1 in-flight chunk per job (max fairness)
        - prefetch=2: allow two chunks in-flight per job (better throughput when few jobs)

        Returns the claimed chunk_id, or None if none are available.
        """
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            pf = max(1, int(prefetch or 1))

            # Serialize claims per job to avoid races where multiple workers
            # simultaneously observe the same doing-count and over-claim.
            # (Row-level locking on the parent job is cheap and safe.)
            cur.execute("SELECT 1 FROM run_all_jobs WHERE id = %s FOR UPDATE", (job_id,))

            # Enforce prefetch limit: claim a todo chunk only if currently
            # doing_count < pf.
            # Atomic claim using UPDATE..FROM with a CTE.
            cur.execute(
                """
                WITH next AS (
                    SELECT id
                    FROM run_all_job_chunks
                    WHERE job_id = %s
                      AND status = 'todo'
                      AND (
                        SELECT COUNT(1) FROM run_all_job_chunks d
                        WHERE d.job_id = %s
                          AND d.status = 'doing'
                      ) < %s
                    ORDER BY chunk_index ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE run_all_job_chunks c
                SET status = 'doing',
                    started_at = COALESCE(started_at, now())
                FROM next
                WHERE c.id = next.id
                RETURNING c.id
                """,
                (job_id, job_id, pf),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return None
            return int(row[0])
        except Exception:
            _safe_rollback(conn)
            raise

    def mark_chunk_done(self, chunk_id: int) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE run_all_job_chunks
                SET status = 'done',
                    finished_at = COALESCE(finished_at, now())
                WHERE id = %s
                """,
                (int(chunk_id),),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def mark_chunk_failed(self, chunk_id: int, *, error: str) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE run_all_job_chunks
                SET status = 'failed',
                    finished_at = COALESCE(finished_at, now()),
                    error = %s
                WHERE id = %s
                """,
                (str(error)[:8000], int(chunk_id)),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def get_active_job_for_sr(self, sr_id: str) -> Optional[Dict[str, Any]]:
        """Return the active job (queued/running/paused) for an SR if it exists."""
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id
                FROM run_all_jobs
                WHERE sr_id = %s
                  AND status IN ('queued', 'running', 'paused')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (sr_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self.get_job(str(row[0]))
        except Exception:
            _safe_rollback(conn)
            raise

    def count_active_jobs(self) -> int:
        """Return number of active run-all jobs (queued/running/paused)."""
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(1)
                FROM run_all_jobs
                WHERE status IN ('queued', 'running', 'paused')
                """
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            _safe_rollback(conn)
            raise

    def list_active_jobs_for_srs(self, sr_ids: list[str]) -> list[Dict[str, Any]]:
        """List active (queued/running/paused) jobs for the given SR ids."""
        if not sr_ids:
            return []
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, sr_id, step, created_by, model, status, total, done, skipped, failed,
                       phase, error, meta, created_at, started_at, finished_at
                FROM run_all_jobs
                WHERE sr_id = ANY(%s)
                  AND status IN ('queued', 'running', 'paused')
                ORDER BY created_at DESC
                """,
                (sr_ids,),
            )
            rows = cur.fetchall() or []
            cols = [d[0] for d in cur.description]
            out: list[Dict[str, Any]] = []
            for row in rows:
                job = {cols[i]: row[i] for i in range(len(cols))}
                # parse meta
                if isinstance(job.get("meta"), str):
                    try:
                        job["meta"] = json.loads(job["meta"])  # type: ignore
                    except Exception:
                        pass
                for k in ("created_at", "started_at", "finished_at"):
                    v = job.get(k)
                    if isinstance(v, datetime):
                        job[k] = v.isoformat()
                if job.get("id") is not None:
                    job["job_id"] = str(job.pop("id"))
                out.append(job)
            return out
        except Exception:
            _safe_rollback(conn)
            raise

    def set_paused(self, job_id: str, paused: bool) -> None:
        """Set paused/running status.

        We model pause as a status string so the UI can reflect it and workers can
        cooperate.
        """
        if paused:
            self.set_status(job_id, "paused")
        else:
            # Resume to running (do not touch started_at)
            self.set_status(job_id, "running")

    def is_paused(self, job_id: str) -> bool:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute("SELECT status FROM run_all_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                return False
            return str(row[0]).lower() == "paused"
        except Exception:
            _safe_rollback(conn)
            raise

    def create_job(
        self,
        *,
        sr_id: str,
        step: str,
        created_by: str,
        model: Optional[str],
        meta: Dict[str, Any],
        total: int,
    ) -> str:
        conn = None
        jid = uuid.uuid4()
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO run_all_jobs (id, sr_id, step, created_by, model, status, total, meta)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    str(jid),
                    sr_id,
                    step,
                    created_by,
                    model,
                    "queued",
                    int(total),
                    json.dumps(meta or {}),
                ),
            )
            conn.commit()
            return str(jid)
        except Exception:
            _safe_rollback(conn)
            raise

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, sr_id, step, created_by, model, status, total, done, skipped, failed,
                       phase, error, meta, created_at, started_at, finished_at
                FROM run_all_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            out = {cols[i]: row[i] for i in range(len(cols))}
            # parse meta
            if isinstance(out.get("meta"), str):
                try:
                    out["meta"] = json.loads(out["meta"])  # type: ignore
                except Exception:
                    pass
            # datetimes to iso
            for k in ("created_at", "started_at", "finished_at"):
                v = out.get(k)
                if isinstance(v, datetime):
                    out[k] = v.isoformat()
            # uuid to str
            if out.get("id") is not None:
                out["job_id"] = str(out.pop("id"))
            return out
        except Exception:
            _safe_rollback(conn)
            raise

    def set_status(self, job_id: str, status: str, *, error: Optional[str] = None) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            now = datetime.utcnow().isoformat()
            if status == "running":
                cur.execute(
                    """
                    UPDATE run_all_jobs
                    SET status = %s, started_at = COALESCE(started_at, %s), error = %s
                    WHERE id = %s
                    """,
                    (status, now, error, job_id),
                )
            elif status in ("done", "failed", "canceled"):
                cur.execute(
                    """
                    UPDATE run_all_jobs
                    SET status = %s, finished_at = COALESCE(finished_at, %s), error = %s
                    WHERE id = %s
                    """,
                    (status, now, error, job_id),
                )
            else:
                cur.execute(
                    "UPDATE run_all_jobs SET status = %s, error = %s WHERE id = %s",
                    (status, error, job_id),
                )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def update_phase(self, job_id: str, phase: str) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                "UPDATE run_all_jobs SET phase = %s WHERE id = %s",
                (phase, job_id),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def set_total(self, job_id: str, total: int) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                "UPDATE run_all_jobs SET total = %s WHERE id = %s",
                (int(total), job_id),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def inc_counts(self, job_id: str, *, done: int = 0, skipped: int = 0, failed: int = 0) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE run_all_jobs
                SET done = done + %s,
                    skipped = skipped + %s,
                    failed = failed + %s
                WHERE id = %s
                """,
                (int(done), int(skipped), int(failed), job_id),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise

    def mark_canceled(self, job_id: str) -> None:
        self.set_status(job_id, "canceled")

    def is_canceled(self, job_id: str) -> bool:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute("SELECT status FROM run_all_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                return False
            return str(row[0]).lower() == "canceled"
        except Exception:
            _safe_rollback(conn)
            raise

    def add_error(self, job_id: str, *, citation_id: Optional[int], stage: str, error: str) -> None:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO run_all_job_errors (job_id, citation_id, stage, error)
                VALUES (%s, %s, %s, %s)
                """,
                (job_id, int(citation_id) if citation_id is not None else None, stage, error[:8000]),
            )
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise


run_all_repo = RunAllRepo()
