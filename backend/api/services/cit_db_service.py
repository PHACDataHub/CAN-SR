"""
Consolidated Postgres service.

This module centralizes all Postgres helpers previously split across
`core.postgres.py` and some router modules (citations/screen/extract).
Routers should import the service instance `cits_dp_service` and call the
methods they need.

All blocking DB operations are synchronous and intended to be run with
`fastapi.concurrency.run_in_threadpool` when called from async routes.

Methods raise RuntimeError when psycopg2 is not available so callers
can surface a 503 with an actionable message.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

# psycopg2 is optional in some deploy/test contexts.
# Per module docstring contract: methods should raise RuntimeError when psycopg2
# is unavailable so routers can surface a 503.
try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
except Exception:  # pragma: no cover
    psycopg2 = None
import json
import re
import os
import io
import csv
import urllib.parse as up
import hashlib
from datetime import datetime
import uuid

# Local settings import (for POSTGRES_ADMIN_DSN / DATABASE_URL usage)
try:
    from ..core.config import settings
except Exception:
    settings = None

from .postgres_auth import postgres_server
from ..criteria.context import resolve_source_value
from .citation_deduplication_service import calculate_duplicate_statuses
from .citation_duplicate_review_service import suggest_survivor

try:
    from .azure_openai_client import azure_openai_client
except Exception:
    azure_openai_client = None


def _safe_rollback(conn) -> None:
    """Best-effort rollback.

    psycopg2 connections become unusable after an error until rollback.
    We share a single connection via postgres_server, so failing to rollback
    poisons unrelated endpoints.
    """
    try:
        if conn:
            conn.rollback()
    except Exception:
        pass


def _derive_agent_run_cost_usd(run: dict[str, Any]) -> float | None:
    raw_cost_usd = run.get('cost_usd')
    if raw_cost_usd is not None:
        try:
            return float(raw_cost_usd)
        except Exception:
            return None

    if azure_openai_client is None:
        return None

    raw_input_tokens = run.get('input_tokens')
    raw_output_tokens = run.get('output_tokens')
    try:
        prompt_tokens = int(raw_input_tokens or 0)
        completion_tokens = int(raw_output_tokens or 0)
    except Exception:
        return None

    if prompt_tokens < 0 or completion_tokens < 0:
        return None
    if prompt_tokens == 0 and completion_tokens == 0:
        return None

    raw_model = run.get('model')
    model = raw_model if isinstance(raw_model, str) else None
    try:
        rates = azure_openai_client.get_model_pricing_usd(model)
        prompt_cost_usd = (
            Decimal(prompt_tokens) /
            Decimal('1000')
        ) * rates['prompt']
        completion_cost_usd = (
            Decimal(completion_tokens) / Decimal('1000')
        ) * rates['completion']
        total_cost_usd = prompt_cost_usd + completion_cost_usd
        return float(total_cost_usd.quantize(Decimal('0.000001')))
    except Exception:
        return None


def _screening_run_area(pipeline: Any, stage: Any) -> str:
    pipeline_norm = str(pipeline or '').strip().lower()
    stage_norm = str(stage or '').strip().lower()

    if pipeline_norm == 'title_abstract':
        prefix = 'l1'
    elif pipeline_norm == 'fulltext':
        prefix = 'l2'
    else:
        prefix = 'other'

    if not stage_norm:
        return prefix
    return f'{prefix}_{stage_norm}'


# -----------------------
# Basic column helpers
# -----------------------
def snake_case(name: str, max_len: int = 63) -> str:
    if not name:
        return ''
    s = name.strip().lower()
    s = re.sub(r'[^\w]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    if re.match(r'^\d', s):
        s = f"c_{s}"
    return s[:max_len]


def snake_case_param(name: str) -> str:
    core = snake_case(name, max_len=52)
    col = f"llm_param_{core}" if core else 'llm_param_param'
    return col[:60]


def snake_case_column(name: str) -> str:
    core = snake_case(name, max_len=56)
    col = f"llm_{core}" if core else 'llm_col'
    return col[:60]


# -----------------------
# Identifier helpers
# -----------------------
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def _validate_ident(name: str, kind: str = 'identifier') -> str:
    """Validate a Postgres identifier we plan to interpolate into SQL.

    We keep this intentionally strict (letters/digits/underscore, max 63 chars)
    because table names are embedded into SQL in several places.
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid {kind}: empty")
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid {kind}: {name!r}")
    return name


# -----------------------
# Connection & DSN helpers
# -----------------------
def parse_dsn(dsn: str) -> dict[str, str]:
    """
    Extract host/port/user/password metadata from a libpq DSN or URL.
    """
    result: dict[str, str] = {}
    try:
        if '=' in (dsn or '') and '://' not in (dsn or ''):
            parts = dsn.split()
            for p in parts:
                if '=' in p:
                    k, v = p.split('=', 1)
                    result[k] = v
        else:
            parsed = up.urlparse(dsn)
            result['host'] = parsed.hostname or ''
            result['port'] = str(parsed.port) if parsed.port else ''
            result['user'] = parsed.username or ''
            result['password'] = parsed.password or ''
    except Exception:
        pass
    return result


def _construct_db_dsn_from_admin(admin_dsn: str, db_name: str) -> str:
    """
    Given an admin DSN (URL or key=value string), return a DSN pointing to db_name.
    """
    if '://' in (admin_dsn or ''):
        parsed = up.urlparse(admin_dsn)
        new_path = '/' + db_name
        new_parsed = parsed._replace(path=new_path)
        return up.urlunparse(new_parsed)
    else:
        if 'dbname=' in (admin_dsn or ''):
            return re.sub(r'dbname=[^ ]+', f"dbname={db_name}", admin_dsn)
        else:
            return f"{admin_dsn} dbname={db_name}"

# -----------------------
# Citations Postgres DB service
# -----------------------


class CitsDPService:
    """
    A blocking (psycopg2) Postgres service for operations on screening/citations DBs.
    Routers should call these methods within run_in_threadpool.
    """

    def __init__(self):
        # nothing stateful for now; keep class for ergonomics and easier testing
        pass

    def _require_psycopg2(self) -> None:
        if psycopg2 is None:
            raise RuntimeError(
                'psycopg2 is not installed. Install backend dependencies (requirements.txt) '
                'or run with the docker backend image.',
            )

    # -----------------------
    # Schema helpers
    # -----------------------
    def table_exists(self, table_name: str = 'citations') -> bool:
        """Return True if a public table exists.

        NOTE: We intentionally use runtime schema evolution (ALTER TABLE ...)
        throughout CAN-SR, so callers need a safe way to check existence before
        attempting to add columns.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
                LIMIT 1
                """,
                (table_name,),
            )
            return cur.fetchone() is not None
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def ensure_step_validation_columns(self, table_name: str = 'citations') -> None:
        """Ensure step-level validation columns exist for a screening table.

        CAN-SR uses per-upload screening tables, so we create these columns on
        those tables (not just a single shared citations table).

        This is intentionally NOT backwards-compatible: it will eagerly add the
        columns to whatever table is passed.
        """
        if not self.table_exists(table_name):
            return

        # L1 (Title/Abstract)
        self.create_column('l1_validated_by', 'TEXT', table_name=table_name)
        self.create_column(
            'l1_validated_at', 'TIMESTAMPTZ',
            table_name=table_name,
        )

        # L2 (Full Text)
        self.create_column('l2_validated_by', 'TEXT', table_name=table_name)
        self.create_column(
            'l2_validated_at', 'TIMESTAMPTZ',
            table_name=table_name,
        )

        # Parameters / extraction
        self.create_column(
            'parameters_validated_by',
            'TEXT', table_name=table_name,
        )
        self.create_column(
            'parameters_validated_at',
            'TIMESTAMPTZ', table_name=table_name,
        )

    def cleanup_set_answer_validation_metadata(
        self,
        table_name: str,
        step: str,
        *,
        execute: bool = False,
    ) -> dict[str, Any]:
        """Report or clear legacy validation metadata attributable to Set Answer.

        Set Answer historically marked rows as validated without provenance.  The
        only safe historical scope available is rows whose stage-specific human
        answer explicitly carries ``source=retrospective_validation``.  This
        command is therefore dry-run by default and requires an explicit execute
        flag; it never runs implicitly during normal requests.
        """
        table_name = _validate_ident(str(table_name or ''), kind='table_name')
        step = str(step or '').strip().lower()
        if step not in {'l1', 'l2', 'parameters'}:
            raise ValueError('step must be l1, l2, or parameters')
        validation_col = f'{step}_validations'
        validated_by_col = f'{step}_validated_by'
        validated_at_col = f'{step}_validated_at'
        columns = {
            str(row.get('column_name'))
            for row in self.get_table_columns(table_name)
            if row.get('column_name')
        }
        human_prefix = 'human_param_' if step == 'parameters' else f'human_{step}_'
        human_cols = sorted(c for c in columns if c.startswith(human_prefix))
        metadata_cols = [
            c for c in (
                validation_col, validated_by_col, validated_at_col,
            ) if c in columns
        ]
        if not human_cols or not metadata_cols:
            return {'table_name': table_name, 'step': step, 'candidates': 0, 'cleared': 0, 'dry_run': not execute}

        source_checks = ' OR '.join(
            f'COALESCE("{col}"->>\'source\', \'\') = %s' for col in human_cols
        )
        params = [*(['retrospective_validation'] * len(human_cols))]
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                f'''SELECT COUNT(*) FROM "{table_name}"
                    WHERE ({source_checks})
                      AND ({' OR '.join(f'"{col}" IS NOT NULL' for col in metadata_cols)})''',
                params,
            )
            candidates = int((cur.fetchone() or [0])[0] or 0)
            cleared = 0
            if execute and candidates:
                assignments = ', '.join(
                    f'"{col}" = NULL' for col in metadata_cols
                )
                cur.execute(
                    f'''UPDATE "{table_name}" SET {assignments}
                        WHERE ({source_checks})
                          AND ({' OR '.join(f'"{col}" IS NOT NULL' for col in metadata_cols)})''',
                    [*params, *params],
                )
                cleared = int(cur.rowcount or 0)
            if execute:
                conn.commit()
            return {
                'table_name': table_name, 'step': step,
                'candidates': candidates, 'cleared': cleared,
                'dry_run': not execute,
            }
        except Exception:
            _safe_rollback(conn)
            raise

    def ensure_screening_agent_runs_table(self) -> None:
        """Ensure the normalized agent-run storage table exists.

        We keep it in the shared Postgres DB (public schema). Because CAN-SR uses
        per-upload screening tables (each with its own id sequence), we store
        both the `sr_id` and the screening `table_name` alongside `citation_id`.
        """
        conn = None
        try:
            self._require_psycopg2()
            conn = postgres_server.conn
            cur = conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS screening_agent_runs (
                    id TEXT PRIMARY KEY,
                    sr_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    citation_id INT NOT NULL,
                    pipeline TEXT NOT NULL,
                    criterion_key TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    answer TEXT,
                    confidence DOUBLE PRECISION,
                    rationale TEXT,
                    raw_response TEXT,
                    model TEXT,
                    prompt_version TEXT,
                    temperature DOUBLE PRECISION,
                    top_p DOUBLE PRECISION,
                    seed INT,
                    latency_ms INT,
                    input_tokens INT,
                    output_tokens INT,
                    cost_usd DOUBLE PRECISION,
                    guardrails JSONB,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """,
            )

            # Runtime schema evolution for existing deployments
            try:
                cur.execute(
                    'ALTER TABLE screening_agent_runs ADD COLUMN IF NOT EXISTS guardrails JSONB',
                )
            except Exception:
                try:
                    cur.execute(
                        'ALTER TABLE screening_agent_runs ADD COLUMN guardrails JSONB',
                    )
                except Exception:
                    pass

            # A couple of pragmatic indexes for common lookups.
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_screening_agent_runs_citation
                ON screening_agent_runs (sr_id, table_name, citation_id, pipeline)
                """,
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_screening_agent_runs_criterion
                ON screening_agent_runs (sr_id, pipeline, criterion_key, stage)
                """,
            )

            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def ensure_agentic_screening_schema(self) -> None:
        """One-call bootstrap for agentic screening.

        This is safe to call at startup (creates only global tables), and can
        also be called by endpoints before use.
        """
        self.ensure_screening_agent_runs_table()

    def ensure_parameter_extraction_runs_table(self) -> None:
        """Ensure the normalized parameter-extraction run storage table exists."""
        conn = None
        try:
            self._require_psycopg2()
            conn = postgres_server.conn
            cur = conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS parameter_extraction_runs (
                    id TEXT PRIMARY KEY,
                    sr_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    citation_id INT NOT NULL,
                    parameter_key TEXT NOT NULL,
                    parameter_name TEXT NOT NULL,
                    found BOOLEAN,
                    value TEXT,
                    explanation TEXT,
                    evidence_sentences JSONB,
                    evidence_tables JSONB,
                    evidence_figures JSONB,
                    raw_response TEXT,
                    model TEXT,
                    prompt_version TEXT,
                    temperature DOUBLE PRECISION,
                    top_p DOUBLE PRECISION,
                    seed INT,
                    latency_ms INT,
                    input_tokens INT,
                    output_tokens INT,
                    cost_usd DOUBLE PRECISION,
                    guardrails JSONB,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """,
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parameter_extraction_runs_citation
                ON parameter_extraction_runs (sr_id, table_name, citation_id)
                """,
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parameter_extraction_runs_parameter
                ON parameter_extraction_runs (sr_id, table_name, parameter_key)
                """,
            )

            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    # -----------------------
    # Agent-run persistence
    # -----------------------
    def insert_screening_agent_run(self, run: dict[str, Any]) -> str:
        """Insert a single screening_agent_runs row.

        Expected keys (most optional):
        - sr_id, table_name, citation_id, pipeline, criterion_key, stage
        - answer, confidence, rationale, raw_response
        - model, prompt_version, temperature, top_p, seed
        - latency_ms, input_tokens, output_tokens, cost_usd

        Returns the generated run id.
        """
        self._require_psycopg2()
        self.ensure_screening_agent_runs_table()

        run_id = str(run.get('id') or uuid.uuid4())
        sr_id = str(run.get('sr_id') or '')
        table_name = str(run.get('table_name') or '')
        citation_id = int(run.get('citation_id') or 0)
        pipeline = str(run.get('pipeline') or '')
        criterion_key = str(run.get('criterion_key') or '')
        stage = str(run.get('stage') or '')

        if not (sr_id and table_name and citation_id and pipeline and criterion_key and stage):
            raise ValueError(
                'insert_screening_agent_run missing required fields',
            )

        conn = None
        try:
            derived_cost_usd = _derive_agent_run_cost_usd(run)
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO screening_agent_runs (
                    id, sr_id, table_name, citation_id, pipeline, criterion_key, stage,
                    answer, confidence, rationale, raw_response,
                    model, prompt_version, temperature, top_p, seed,
                    latency_ms, input_tokens, output_tokens, cost_usd, guardrails, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    run_id,
                    sr_id,
                    table_name,
                    citation_id,
                    pipeline,
                    criterion_key,
                    stage,
                    run.get('answer'),
                    run.get('confidence'),
                    run.get('rationale'),
                    run.get('raw_response'),
                    run.get('model'),
                    run.get('prompt_version'),
                    run.get('temperature'),
                    run.get('top_p'),
                    run.get('seed'),
                    run.get('latency_ms'),
                    run.get('input_tokens'),
                    run.get('output_tokens'),
                    derived_cost_usd,
                    json.dumps(run.get('guardrails')) if run.get(
                        'guardrails',
                    ) is not None else None,
                    run.get('created_at') or datetime.utcnow().isoformat() + 'Z',
                ),
            )
            conn.commit()
            return run_id
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def insert_parameter_extraction_run(self, run: dict[str, Any]) -> str:
        """Insert a single parameter_extraction_runs row."""
        self._require_psycopg2()
        self.ensure_parameter_extraction_runs_table()

        run_id = str(run.get('id') or uuid.uuid4())
        sr_id = str(run.get('sr_id') or '')
        table_name = str(run.get('table_name') or '')
        citation_id = int(run.get('citation_id') or 0)
        parameter_key = str(run.get('parameter_key') or '')
        parameter_name = str(run.get('parameter_name') or '')

        if not (sr_id and table_name and citation_id and parameter_key and parameter_name):
            raise ValueError(
                'insert_parameter_extraction_run missing required fields',
            )

        conn = None
        try:
            derived_cost_usd = _derive_agent_run_cost_usd(run)
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO parameter_extraction_runs (
                    id, sr_id, table_name, citation_id, parameter_key, parameter_name,
                    found, value, explanation,
                    evidence_sentences, evidence_tables, evidence_figures,
                    raw_response,
                    model, prompt_version, temperature, top_p, seed,
                    latency_ms, input_tokens, output_tokens, cost_usd, guardrails, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    run_id,
                    sr_id,
                    table_name,
                    citation_id,
                    parameter_key,
                    parameter_name,
                    run.get('found'),
                    run.get('value'),
                    run.get('explanation'),
                    json.dumps(run.get('evidence_sentences') or []),
                    json.dumps(run.get('evidence_tables') or []),
                    json.dumps(run.get('evidence_figures') or []),
                    run.get('raw_response'),
                    run.get('model'),
                    run.get('prompt_version'),
                    run.get('temperature'),
                    run.get('top_p'),
                    run.get('seed'),
                    run.get('latency_ms'),
                    run.get('input_tokens'),
                    run.get('output_tokens'),
                    derived_cost_usd,
                    json.dumps(run.get('guardrails')) if run.get(
                        'guardrails',
                    ) is not None else None,
                    run.get('created_at') or datetime.utcnow().isoformat() + 'Z',
                ),
            )
            conn.commit()
            return run_id
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def agent_runs_exist(self, *, sr_id: str, table_name: str, pipeline: str) -> bool:
        """Return True if we have any normalized agent runs for this SR+table+pipeline."""

        self._require_psycopg2()
        self.ensure_screening_agent_runs_table()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 1
                FROM screening_agent_runs
                WHERE sr_id=%s AND table_name=%s AND pipeline=%s
                LIMIT 1
                """,
                (str(sr_id), str(table_name), str(pipeline)),
            )
            return cur.fetchone() is not None
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def legacy_llm_outputs_exist_for_step(
        self,
        *,
        table_name: str,
        criteria_parsed: dict[str, Any],
        step: str,
    ) -> bool:
        """Return True if any legacy llm_* JSONB columns for this step contain data."""

        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        if not self.table_exists(table_name):
            return False

        step_norm = str(step or '').lower().strip()
        if step_norm not in {'l1', 'l2'}:
            return False

        qs = (((criteria_parsed or {}).get(step_norm) or {}).get('questions') or [])
        if not isinstance(qs, list) or not qs:
            return False

        # Determine which llm_* columns exist
        cols_meta = self.get_table_columns(table_name)
        existing_cols = {
            c.get('column_name')
            for c in cols_meta if c and c.get('column_name')
        }
        llm_cols = []
        for q in qs:
            if not isinstance(q, str) or not q.strip():
                continue
            col = snake_case_column(q)
            if col in existing_cols:
                llm_cols.append(col)
        if not llm_cols:
            return False

        # Any non-null legacy output?
        or_sql = ' OR '.join([f'"{c}" IS NOT NULL' for c in llm_cols])
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(f'SELECT 1 FROM "{table_name}" WHERE {or_sql} LIMIT 1')
            return cur.fetchone() is not None
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def legacy_needs_rerun(
        self,
        *,
        sr_id: str,
        table_name: str,
        criteria_parsed: dict[str, Any],
        step: str,
    ) -> bool:
        """Return True when legacy llm_* outputs exist but normalized runs do not.

        This is the signal to:
        - warn the user that they must run run-all
        - auto-enable force overwrite for run-all
        """

        step_norm = str(step or '').lower().strip()
        if step_norm not in {'l1', 'l2'}:
            return False
        pipeline = 'title_abstract' if step_norm == 'l1' else 'fulltext'
        legacy = self.legacy_llm_outputs_exist_for_step(
            table_name=table_name, criteria_parsed=criteria_parsed, step=step_norm,
        )
        if not legacy:
            return False
        return not self.agent_runs_exist(sr_id=sr_id, table_name=table_name, pipeline=pipeline)

    def list_latest_agent_runs(
        self,
        *,
        sr_id: str,
        table_name: str,
        citation_ids: list[int],
        pipeline: str,
    ) -> list[dict[str, Any]]:
        """Return latest agent runs per (citation_id, criterion_key, stage) for a set of citations.

        This is designed for list pages where we need to compute "needs validation"
        without loading full raw responses.
        """
        self._require_psycopg2()
        self.ensure_screening_agent_runs_table()

        sr_id = str(sr_id or '')
        table_name = str(table_name or '')
        pipeline = str(pipeline or '')

        ids: list[int] = []
        for i in citation_ids or []:
            try:
                ids.append(int(i))
            except Exception:
                continue
        if not (sr_id and table_name and pipeline and ids):
            return []

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute(
                """
                WITH latest_runs AS (
                    SELECT DISTINCT ON (citation_id, criterion_key, stage)
                        id,
                        sr_id,
                        table_name,
                        citation_id,
                        pipeline,
                        criterion_key,
                        stage,
                        answer,
                        confidence,
                        rationale,
                        guardrails,
                        model,
                        prompt_version,
                        temperature,
                        top_p,
                        seed,
                        latency_ms,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        created_at
                    FROM screening_agent_runs
                    WHERE sr_id = %s
                      AND table_name = %s
                      AND pipeline = %s
                      AND citation_id = ANY(%s)
                    ORDER BY citation_id, criterion_key, stage, created_at DESC
                ),
                aggregated_costs AS (
                    SELECT
                        citation_id,
                        criterion_key,
                        stage,
                        COALESCE(SUM(cost_usd), 0) AS total_cost_usd
                    FROM screening_agent_runs
                    WHERE sr_id = %s
                      AND table_name = %s
                      AND pipeline = %s
                      AND citation_id = ANY(%s)
                    GROUP BY citation_id, criterion_key, stage
                )
                SELECT
                    latest_runs.id,
                    latest_runs.sr_id,
                    latest_runs.table_name,
                    latest_runs.citation_id,
                    latest_runs.pipeline,
                    latest_runs.criterion_key,
                    latest_runs.stage,
                    latest_runs.answer,
                    latest_runs.confidence,
                    latest_runs.rationale,
                    latest_runs.guardrails,
                    latest_runs.model,
                    latest_runs.prompt_version,
                    latest_runs.temperature,
                    latest_runs.top_p,
                    latest_runs.seed,
                    latest_runs.latency_ms,
                    latest_runs.input_tokens,
                    latest_runs.output_tokens,
                    latest_runs.cost_usd,
                    aggregated_costs.total_cost_usd,
                    latest_runs.created_at
                FROM latest_runs
                LEFT JOIN aggregated_costs
                  ON aggregated_costs.citation_id = latest_runs.citation_id
                 AND aggregated_costs.criterion_key = latest_runs.criterion_key
                 AND aggregated_costs.stage = latest_runs.stage
                ORDER BY latest_runs.citation_id, latest_runs.criterion_key, latest_runs.stage
                """,
                (
                    sr_id, table_name, pipeline, ids,
                    sr_id, table_name, pipeline, ids,
                ),
            )

            rows = cur.fetchall() or []
            return [dict(r) for r in rows if r]
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def summarize_costs_for_sr(self, sr_id: str) -> dict[str, Any]:
        self._require_psycopg2()
        self.ensure_screening_agent_runs_table()
        self.ensure_parameter_extraction_runs_table()

        sr_id = str(sr_id or '').strip()
        if not sr_id:
            return {
                'sr_id': '',
                'currency': 'USD',
                'totals': {
                    'l1': 0.0,
                    'l2': 0.0,
                    'extraction': 0.0,
                    'other': 0.0,
                    'grand_total': 0.0,
                },
                'breakdown': {},
            }

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT
                    pipeline,
                    stage,
                    COALESCE(SUM(cost_usd), 0) AS total_cost_usd
                FROM screening_agent_runs
                WHERE sr_id = %s
                  AND cost_usd IS NOT NULL
                GROUP BY pipeline, stage
                ORDER BY pipeline, stage
                """,
                (sr_id,),
            )
            rows = cur.fetchall() or []

            breakdown: dict[str, Decimal] = {}
            totals = {
                'l1': Decimal('0'),
                'l2': Decimal('0'),
                'extraction': Decimal('0'),
                'other': Decimal('0'),
            }
            grand_total = Decimal('0')

            for row in rows:
                area = _screening_run_area(
                    row.get('pipeline'), row.get('stage'),
                )
                total = row.get('total_cost_usd') or Decimal('0')
                if not isinstance(total, Decimal):
                    total = Decimal(str(total))

                breakdown[area] = breakdown.get(area, Decimal('0')) + total
                grand_total += total

                if area.startswith('l1'):
                    totals['l1'] += total
                elif area.startswith('l2'):
                    totals['l2'] += total
                else:
                    totals['other'] += total

            cur.execute(
                """
                SELECT
                    parameter_key,
                    COALESCE(SUM(cost_usd), 0) AS total_cost_usd
                FROM parameter_extraction_runs
                WHERE sr_id = %s
                  AND cost_usd IS NOT NULL
                GROUP BY parameter_key
                ORDER BY parameter_key
                """,
                (sr_id,),
            )
            extraction_rows = cur.fetchall() or []
            for row in extraction_rows:
                parameter_key = str(row.get('parameter_key') or '').strip()
                if not parameter_key:
                    continue
                total = row.get('total_cost_usd') or Decimal('0')
                if not isinstance(total, Decimal):
                    total = Decimal(str(total))
                breakdown[f'extraction.{parameter_key}'] = total
                totals['extraction'] += total
                grand_total += total

            return {
                'sr_id': sr_id,
                'currency': 'USD',
                'totals': {
                    'l1': round(float(totals['l1']), 4),
                    'l2': round(float(totals['l2']), 4),
                    'extraction': round(float(totals['extraction']), 4),
                    'other': round(float(totals['other']), 4),
                    'grand_total': round(float(grand_total), 4),
                },
                'breakdown': {k: round(float(v), 4) for k, v in breakdown.items()},
            }
        except Exception:
            _safe_rollback(conn)
            raise

    def summarize_parameter_extraction_costs(
        self,
        *,
        sr_id: str,
        table_name: str,
        citation_ids: list[int],
    ) -> dict[str, Any]:
        self._require_psycopg2()
        self.ensure_parameter_extraction_runs_table()

        sr_id = str(sr_id or '').strip()
        table_name = str(table_name or '').strip()

        normalized_citation_ids: list[int] = []
        seen_citation_ids: set[int] = set()
        for citation_id in citation_ids or []:
            try:
                parsed_citation_id = int(citation_id)
            except Exception:
                continue
            if parsed_citation_id <= 0 or parsed_citation_id in seen_citation_ids:
                continue
            seen_citation_ids.add(parsed_citation_id)
            normalized_citation_ids.append(parsed_citation_id)

        if not (sr_id and table_name and normalized_citation_ids):
            return {
                'sr_id': sr_id,
                'table_name': table_name,
                'currency': 'USD',
                'costs': [],
            }

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT
                    citation_id,
                    parameter_key,
                    COALESCE(SUM(cost_usd), 0) AS total_cost_usd
                FROM parameter_extraction_runs
                WHERE sr_id = %s
                  AND table_name = %s
                  AND citation_id = ANY(%s)
                  AND cost_usd IS NOT NULL
                GROUP BY citation_id, parameter_key
                ORDER BY citation_id, parameter_key
                """,
                (sr_id, table_name, normalized_citation_ids),
            )
            rows = cur.fetchall() or []

            costs_by_citation_id: dict[int, dict[str, Any]] = {
                citation_id: {
                    'sr_id': sr_id,
                    'table_name': table_name,
                    'citation_id': citation_id,
                    'currency': 'USD',
                    'total_cost_usd': 0.0,
                    'parameters': {},
                }
                for citation_id in normalized_citation_ids
            }

            totals_by_citation_id: dict[int, Decimal] = {
                citation_id: Decimal('0') for citation_id in normalized_citation_ids
            }

            for row in rows:
                try:
                    citation_id = int(row.get('citation_id') or 0)
                except Exception:
                    continue
                if citation_id not in costs_by_citation_id:
                    continue

                parameter_key = str(row.get('parameter_key') or '').strip()
                if not parameter_key:
                    continue

                amount = row.get('total_cost_usd') or Decimal('0')
                if not isinstance(amount, Decimal):
                    amount = Decimal(str(amount))

                totals_by_citation_id[citation_id] += amount
                costs_by_citation_id[citation_id]['parameters'][parameter_key] = float(
                    amount,
                )

            for citation_id, total_cost in totals_by_citation_id.items():
                costs_by_citation_id[citation_id]['total_cost_usd'] = float(
                    total_cost,
                )

            return {
                'sr_id': sr_id,
                'table_name': table_name,
                'currency': 'USD',
                'costs': [costs_by_citation_id[citation_id] for citation_id in normalized_citation_ids],
            }
        except Exception:
            _safe_rollback(conn)
            raise

    def confidence_histogram_for_criterion(
        self,
        *,
        sr_id: str,
        table_name: str,
        citation_ids: list[int],
        pipeline: str,
        criterion_key: str,
        human_col: str,
        validations_col: str | None = None,
        legacy_validated_by: str | None = None,
        bins: int = 10,
    ) -> list[dict[str, Any]]:
        """Return a 3-way confidence histogram (unlabelled/agree/disagree) for one criterion.

        This is used by operational dashboards to show how confidence distributions
        shift as humans label citations.

        Notes:
        - Uses latest *screening* run per citation for the given criterion.
        - Uses the citations table's per-criterion JSONB human column (human_{criterion_key}).
          Agreement is a string match on `selected` vs `answer` after trimming.
        - IMPORTANT: "labelled" means a human answer exists in human_{criterion_key}.selected.
          This includes both validated citations AND unvalidated citations with human review.
          Validation status (checkbox) only affects progress tracking, not agreement metrics.
        """

        self._require_psycopg2()
        self.ensure_screening_agent_runs_table()

        sr_id = str(sr_id or '')
        table_name = str(table_name or '')
        pipeline = str(pipeline or '')
        criterion_key = str(criterion_key or '')
        bins = int(bins or 10)
        if bins <= 0:
            bins = 10

        ids: list[int] = []
        for i in citation_ids or []:
            try:
                ids.append(int(i))
            except Exception:
                continue
        if not (sr_id and table_name and pipeline and criterion_key and ids):
            return []

        # Validate identifiers we interpolate into SQL.
        table_name = _validate_ident(table_name, kind='table_name')
        human_col = _validate_ident(str(human_col or ''), kind='column')
        validations_col = str(validations_col or '').strip() or None
        legacy_validated_by = str(legacy_validated_by or '').strip() or None
        if validations_col is not None:
            validations_col = _validate_ident(validations_col, kind='column')
        if legacy_validated_by is not None:
            legacy_validated_by = _validate_ident(
                legacy_validated_by, kind='column',
            )

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Determine which columns exist. We intentionally treat missing human_*
            # columns as "unlabelled" rather than erroring, because the UI should
            # still be able to render a confidence distribution before any human
            # answers have been recorded.
            try:
                existing_cols = {
                    c.get('column_name')
                    for c in self.get_table_columns(table_name)
                }
            except Exception:
                existing_cols = set()

            has_human_col = human_col in existing_cols
            has_validations_col = bool(validations_col) and (
                validations_col in existing_cols
            )
            has_legacy_validated_by = bool(legacy_validated_by) and (
                legacy_validated_by in existing_cols
            )

            human_sel_expr = (
                f"NULLIF(BTRIM(COALESCE((c.\"{human_col}\"->>'selected'), '')), '')"
                if has_human_col
                else 'NULL'
            )

            validated_expr_parts: list[str] = []
            if has_validations_col and validations_col:
                # validations_col is JSONB list; validated if array length > 0.
                validated_expr_parts.append(
                    f"(jsonb_array_length(COALESCE(c.\"{validations_col}\", '[]'::jsonb)) > 0)",
                )
            if has_legacy_validated_by and legacy_validated_by:
                validated_expr_parts.append(
                    f"(NULLIF(BTRIM(COALESCE(c.\"{legacy_validated_by}\", '')), '') IS NOT NULL)",
                )
            validated_expr = ' OR '.join(
                validated_expr_parts,
            ) if validated_expr_parts else 'FALSE'

            # We select the latest screening run per citation_id for this criterion,
            # then bucket by confidence and compute three counts.
            cur.execute(
                f"""
                WITH latest AS (
                    SELECT DISTINCT ON (r.citation_id)
                        r.citation_id,
                        r.answer,
                        r.confidence
                    FROM screening_agent_runs r
                    WHERE r.sr_id = %s
                      AND r.table_name = %s
                      AND r.pipeline = %s
                      AND r.criterion_key = %s
                      AND r.stage = 'screening'
                      AND r.citation_id = ANY(%s)
                    ORDER BY r.citation_id, r.created_at DESC
                ),
                joined AS (
                    SELECT
                        l.citation_id,
                        l.answer,
                        CASE
                          WHEN l.confidence IS NULL THEN 0.0
                          WHEN l.confidence < 0 THEN 0.0
                          WHEN l.confidence > 1 THEN 1.0
                          ELSE l.confidence
                        END AS confidence,
                        {human_sel_expr} AS human_selected
                    FROM latest l
                    JOIN "{table_name}" c ON c.id = l.citation_id
                ),
                binned AS (
                    SELECT
                        LEAST(%s - 1, GREATEST(0, FLOOR(confidence * %s)::int)) AS bin_index,
                        human_selected,
                        NULLIF(BTRIM(COALESCE(answer, '')), '') AS ai_answer
                    FROM joined
                )
                SELECT
                    bin_index,
                    SUM(CASE WHEN human_selected IS NULL THEN 1 ELSE 0 END) AS unlabelled,
                    SUM(CASE WHEN human_selected IS NOT NULL AND ai_answer IS NOT NULL AND human_selected = ai_answer THEN 1 ELSE 0 END) AS agree,
                    SUM(CASE WHEN human_selected IS NOT NULL AND (ai_answer IS NULL OR human_selected <> ai_answer) THEN 1 ELSE 0 END) AS disagree
                FROM binned
                GROUP BY bin_index
                ORDER BY bin_index ASC
                """,
                (sr_id, table_name, pipeline, criterion_key, ids, bins, bins),
            )

            rows = cur.fetchall() or []
            # Normalize to dense bins [0..bins-1] for stable UI.
            by_bin: dict[int, dict[str, int]] = {}
            for r in rows:
                try:
                    bi = int(r.get('bin_index'))
                except Exception:
                    continue
                by_bin[bi] = {
                    'unlabelled': int(r.get('unlabelled') or 0),
                    'agree': int(r.get('agree') or 0),
                    'disagree': int(r.get('disagree') or 0),
                }

            out: list[dict[str, Any]] = []
            for bi in range(bins):
                start = bi / float(bins)
                end = (bi + 1) / float(bins)
                cnts = by_bin.get(bi) or {
                    'unlabelled': 0, 'agree': 0, 'disagree': 0,
                }
                out.append(
                    {
                        'bin_start': start,
                        'bin_end': end,
                        **cnts,
                    },
                )
            return out
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    # -----------------------
    # Low level connection helpers
    # -----------------------

    # -----------------------
    # Generic column ops
    # -----------------------

    def create_column(self, col: str, col_type: str, table_name: str = 'citations') -> None:
        """
        Create column on citations table if it doesn't already exist.
        col should be the exact column name to use (caller may pass snake_case(col)).
        col_type is the SQL type (e.g. TEXT, JSONB).
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(
                    f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" {col_type}',
                )
            except Exception:
                # fallback for PG versions without IF NOT EXISTS
                try:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {col_type}',
                    )
                except Exception:
                    pass
            conn.commit()

        except Exception:
            _safe_rollback(conn)
            raise

        finally:
            if conn:
                pass

    def update_jsonb_column(
        self,
        citation_id: int,
        col: str,
        data: Any,
        table_name: str = 'citations',
    ) -> int:
        """
        Update a JSONB column for a citation. Creates the column if needed.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(
                    f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" JSONB',
                )
            except Exception:
                try:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" JSONB',
                    )
                except Exception:
                    pass
            cur.execute(
                f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (
                    json.dumps(
                        data,
                    ), int(citation_id),
                ),
            )
            rows = cur.rowcount
            conn.commit()

            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def update_text_column(
        self,
        citation_id: int,
        col: str,
        text_value: str,
        table_name: str = 'citations',
    ) -> int:
        """
        Update a TEXT column for a citation. Creates the column if needed.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(
                    f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" TEXT',
                )
            except Exception:
                try:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT',
                    )
                except Exception:
                    pass
            cur.execute(
                f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (
                    text_value, int(
                        citation_id,
                    ),
                ),
            )
            rows = cur.rowcount
            conn.commit()

            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def update_bool_column(
        self,
        citation_id: int,
        col: str,
        bool_value: bool,
        table_name: str = 'citations',
    ) -> int:
        """Update a BOOLEAN column for a citation. Creates the column if needed."""
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(
                    f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" BOOLEAN',
                )
            except Exception:
                try:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" BOOLEAN',
                    )
                except Exception:
                    pass
            cur.execute(
                f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (
                    bool(
                        bool_value,
                    ), int(citation_id),
                ),
            )
            rows = cur.rowcount
            conn.commit()
            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def get_table_columns(self, table_name: str = 'citations') -> list[dict[str, str]]:
        """Return [{name, data_type, udt_name}] for table columns ordered by ordinal_position."""
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT column_name, data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            rows = cur.fetchall() or []
            return [
                {
                    'column_name': str(r.get('column_name')),
                    'data_type': str(r.get('data_type')),
                    'udt_name': str(r.get('udt_name')),
                }
                for r in rows
                if r and r.get('column_name')
            ]
        finally:
            if conn:
                pass

    def list_workspace_citations(
        self,
        table_name: str,
        search: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        columns: list[str] | None = None,
        filters: dict[str, str] | None = None,
        deduplication_fields: list[str] | None = None,
        duplicate_status: str | None = None,
        cached_duplicate_data: dict[str, Any] | None = None,
        calculate_duplicates: bool = True,
        duplicate_threshold: float = 0.70,
    ) -> dict[str, Any]:
        """Return all stable, searchable user-facing citation data.

        Dynamic citation tables have different source schemas.  The display and
        search fields are therefore derived from PostgreSQL metadata instead of
        accepting client-provided identifiers.  This keeps interpolation limited
        to validated, server-owned identifiers.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        excluded = {
            'id', 'created_at', 'updated_at', 'fulltext_url', 'fulltext',
            'fulltext_content', 'screening_decision',
        }
        scalar_types = {
            'character varying', 'character', 'text', 'integer', 'bigint',
            'smallint', 'numeric', 'real', 'double precision', 'date',
            'timestamp without time zone', 'timestamp with time zone',
        }
        conn = None
        try:
            conn = postgres_server.conn
            try:
                cur = conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
            except Exception:
                cur = conn.cursor()
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            metadata = cur.fetchall() or []
            if metadata and not isinstance(metadata[0], dict):
                metadata = [
                    {'column_name': row[0], 'data_type': row[1]}
                    for row in metadata
                ]
            searchable = [
                _validate_ident(str(column['column_name']), kind='column_name')
                for column in metadata
                if str(column.get('data_type')) in scalar_types
                and str(column.get('column_name')) not in excluded
                and not str(column.get('column_name')).startswith(('llm_', 'human_', 'fulltext_'))
            ]
            preferred = [
                'title', 'abstract', 'authors',
                'author', 'doi', 'year', 'publication_year',
            ]
            default_display = [
                'id', 'provenance',
            ] if 'provenance' in searchable else ['id']
            default_display += [
                name for name in preferred if name in searchable and name not in default_display
            ]
            if len(default_display) == 1:
                default_display.extend(searchable[:4])
            requested_columns = columns or default_display
            # The request is presentation state only; metadata-derived searchable
            # fields are the allowlist for every interpolated identifier.
            display = []
            for column in requested_columns:
                if column in {'id', *searchable} and column not in display:
                    display.append(column)
            if 'id' not in display:
                display.insert(0, 'id')
            if len(display) == 1 and default_display != ['id']:
                display = default_display
            requested_sort = str(sort or 'id').strip()
            sort_column = requested_sort if requested_sort in display else 'id'
            sort_direction = str(direction or 'asc').strip().lower()
            if sort_direction not in {'asc', 'desc'}:
                sort_direction = 'asc'

            where_sql = ''
            params: list[Any] = []
            search_value = str(search or '').strip()
            if search_value and searchable:
                escaped = search_value.replace('\\', '\\\\').replace(
                    '%', '\\%',
                ).replace('_', '\\_')
                predicates = [
                    f'CAST("{column}" AS TEXT) ILIKE %s ESCAPE \'\\\'' for column in searchable
                ]
                where_sql = ' WHERE ' + ' OR '.join(predicates)
                params.extend([f'%{escaped}%'] * len(predicates))
            for column, value in (filters or {}).items():
                if column in searchable and str(value).strip():
                    escaped = str(value).strip().replace(
                        '\\', '\\\\',
                    ).replace('%', '\\%').replace('_', '\\_')
                    where_sql += (' AND ' if where_sql else ' WHERE ') + \
                        f'CAST("{column}" AS TEXT) ILIKE %s ESCAPE \'\\\''
                    params.append(f'%{escaped}%')

            cur.execute(
                f'SELECT COUNT(*) FROM "{table_name}"{where_sql}',
                tuple(params),
            )
            count_row = cur.fetchone()
            total_count = int(
                count_row['count'] if isinstance(
                    count_row, dict,
                ) else count_row[0],
            )
            cur.execute(
                f'SELECT COUNT(*), COALESCE(MAX(id), 0) '
                f'FROM "{table_name}"',
            )
            revision_row = cur.fetchone()
            dataset_revision = (
                tuple(revision_row.values()) if isinstance(
                    revision_row, dict,
                ) else tuple(revision_row)
            )
            schema_version = hashlib.sha256(
                json.dumps(
                    [
                        (column['column_name'], column['data_type'])
                        for column in metadata
                    ],
                    separators=(',', ':'),
                ).encode(),
            ).hexdigest()
            query_fingerprint = 'sha256:' + hashlib.sha256(
                json.dumps(
                    {
                        'table_name': table_name,
                        'schema_version': schema_version,
                        'dataset_revision': dataset_revision,
                        'search': search_value.casefold(),
                        'sort': sort_column,
                        'direction': sort_direction,
                        'filters': filters or {},
                        'duplicate_status': duplicate_status or '',
                        'deduplication_fields': deduplication_fields or [],
                    }, sort_keys=True, separators=(',', ':'), default=str,
                ).encode(),
            ).hexdigest()
            configured_match_fields = [
                column for column in (
                    deduplication_fields or [
                        column for column in display
                        if column not in {'id', 'provenance'}
                    ]
                )
                if column in searchable and column not in {'id', 'provenance'}
            ]
            order_sql = (
                f'ORDER BY "id" {sort_direction.upper()}'
                if sort_column == 'id'
                else f'ORDER BY "{sort_column}" {sort_direction.upper()} NULLS LAST, "id" ASC'
            )
            match_columns = list(
                dict.fromkeys(
                    ['id', *configured_match_fields, *display],
                ),
            )
            match_sql = ', '.join(f'"{column}"' for column in match_columns)
            all_rows = None
            can_reuse_display_rows = not where_sql and all(
                field in display for field in configured_match_fields
            )
            if not can_reuse_display_rows:
                cur.execute(
                    f'SELECT {match_sql} FROM "{table_name}" {order_sql}',
                )
                all_rows = cur.fetchall() or []
                if all_rows and not isinstance(all_rows[0], dict):
                    all_rows = [
                        dict(zip(match_columns, row))
                        for row in all_rows
                    ]
            duplicate_data = cached_duplicate_data
            if duplicate_data is None and calculate_duplicates:
                duplicate_data = calculate_duplicate_statuses(
                    all_rows or [], configured_match_fields, duplicate_threshold,
                )
            if duplicate_data is None:
                duplicate_data = {
                    'rows': [
                        {'status': 'not_run', 'group_id': None, 'score': None}
                        for _ in (all_rows or [])
                    ], 'groups': [], 'lookahead': 0,
                }
            duplicate_by_id = {
                row.get('id', index): duplicate
                for index, (row, duplicate) in enumerate(
                    zip(all_rows or [], duplicate_data['rows']),
                )
            }
            groups = []
            select_sql = ', '.join(f'"{column}"' for column in display)
            order_sql = (
                f'ORDER BY "id" {sort_direction.upper()}'
                if sort_column == 'id'
                else f'ORDER BY "{sort_column}" {sort_direction.upper()} NULLS LAST, "id" ASC'
            )
            try:
                cur.execute(
                    f'SELECT {select_sql} FROM "{table_name}"{where_sql} '
                    f'{order_sql}',
                    tuple(params),
                )
                rows = cur.fetchall() or []
            except StopIteration:
                # Lightweight database mocks may provide only the full-dataset
                # result. Production cursors never raise StopIteration here.
                if all_rows is None:
                    raise
                rows = all_rows
            if rows and not isinstance(rows[0], dict):
                rows = [dict(zip(display, row)) for row in rows]
            if all_rows is None and cached_duplicate_data is None and calculate_duplicates:
                all_rows = rows
                duplicate_data = calculate_duplicate_statuses(
                    all_rows,
                    configured_match_fields, duplicate_threshold,
                )
                duplicate_by_id = {
                    row.get('id', index): duplicate
                    for index, (row, duplicate) in enumerate(
                        zip(all_rows, duplicate_data['rows']),
                    )
                }
            elif all_rows is None:
                all_rows = rows
            if cached_duplicate_data is not None:
                duplicate_by_id = {
                    item.get('citation_id', index): item
                    for index, item in enumerate(cached_duplicate_data.get('rows', []))
                }
            groups = [
                {
                    **group,
                    'members': group.get('members') or [
                        {**all_rows[index], **duplicate_data['rows'][index]}
                        for index in range(len(all_rows))
                        if all_rows[index].get('id', index) in group['citation_ids']
                    ],
                    **suggest_survivor(
                        group.get('members') or [
                            {
                                **all_rows[index], **
                                duplicate_data['rows'][index],
                            }
                            for index in range(len(all_rows))
                            if all_rows[index].get('id', index) in group['citation_ids']
                        ],
                    ),
                }
                for group in duplicate_data['groups']
            ]
            for row in rows:
                duplicate = duplicate_by_id.get(
                    row.get('id'), {
                        'status': 'no_match', 'group_id': None, 'score': None,
                    },
                )
                row['duplicate_status'] = duplicate['status']
                row['duplicate_group_id'] = duplicate['group_id']
                row['duplicate_score'] = duplicate['score']
            if duplicate_status in {'exact', 'possible', 'no_match'}:
                rows = [
                    row for row in rows if row['duplicate_status']
                    == duplicate_status
                ]
            return {
                'citations': rows,
                'total_count': len(rows) if duplicate_status in {'exact', 'possible', 'no_match'} else total_count,
                'columns': display,
                'available_columns': ['id'] + searchable,
                'sort': sort_column,
                'direction': sort_direction,
                'query_fingerprint': query_fingerprint,
                'dataset_revision': dataset_revision,
                'duplicate_fields': configured_match_fields,
                'duplicate_lookahead': duplicate_data['lookahead'],
                'duplicate_counts': {
                    status: sum(
                        1 for item in duplicate_data['rows'] if item['status'] == status
                    )
                    for status in ('exact', 'possible', 'no_match')
                },
                'duplicate_groups': groups,
            }
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def load_duplicate_rows(self, table_name: str, fields: list[str], threshold: float = 0.70) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Load the complete dataset in the dedicated deduplication order."""
        table_name = _validate_ident(table_name, kind='table_name')
        columns = [
            item['column_name']
            for item in self.get_table_columns(table_name)
        ]
        fields = [
            field for field in dict.fromkeys(
                fields,
            ) if field in columns and field not in {'id', 'provenance'}
        ]
        conn = postgres_server.conn
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            select_sql = ', '.join('"' + column + '"' for column in columns)
            cur.execute(f'SELECT {select_sql} FROM "{table_name}"')
            rows = cur.fetchall() or []
            rows = [dict(row) for row in rows]
            from .citation_deduplication_service import normalize
            rows.sort(
                key=lambda row: tuple(
                    normalize(row.get(field))
                    for field in fields
                ) + (str(row.get('id', '')),),
            )
            result = calculate_duplicate_statuses(rows, fields, threshold)
            result['rows'] = [
                {**item, 'citation_id': rows[index].get('id', index)}
                for index, item in enumerate(result['rows'])
            ]
            by_id = {
                row.get('id', index): row for index,
                row in enumerate(rows)
            }
            for group in result['groups']:
                members = [
                    {
                        **by_id[citation_id], **next(
                            item for item in result['rows'] if item['citation_id'] == citation_id
                        ),
                    }
                    for citation_id in group['citation_ids'] if citation_id in by_id
                ]
                group['members'] = members
                group.update(suggest_survivor(members))
            return self._dataset_revision(cur, table_name), result
        finally:
            cur.close()

    def _dataset_revision(self, cur, table_name: str) -> tuple[Any, ...]:
        cur.execute(
            f' SELECT COUNT(*), COALESCE(MAX(id), 0) FROM "{table_name}"',
        )
        row = cur.fetchone()
        return tuple(row.values()) if isinstance(row, dict) else tuple(row)

    def clear_columns(self, citation_id: int, columns: list[str], table_name: str = 'citations') -> int:
        """Set provided columns to NULL for a citation. Ignores unknown columns."""
        table_name = _validate_ident(table_name, kind='table_name')
        if not columns:
            return 0
        conn = None
        try:
            # filter to real columns
            existing = {
                c['column_name']
                for c in self.get_table_columns(table_name)
            }
            cols = [c for c in columns if c in existing]
            if not cols:
                return 0

            conn = postgres_server.conn
            cur = conn.cursor()
            set_sql = ', '.join([f'"{c}" = NULL' for c in cols])
            cur.execute(
                f'UPDATE "{table_name}" SET {set_sql} WHERE id = %s', (
                    int(
                        citation_id,
                    ),
                ),
            )
            rows = cur.rowcount
            conn.commit()
            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def delete_citations(
        self, table_name: str, citation_ids: list[int], sr_id: str | None = None,
        expected_revision: Any | None = None,
    ) -> dict[str, Any]:
        """Physically delete the selected citation rows without a confirmation guard."""
        table_name = _validate_ident(table_name, kind='table_name')
        ids = sorted({int(value) for value in citation_ids})
        if not ids:
            return {'deleted_count': 0}
        conn = postgres_server.conn
        cur = conn.cursor()
        try:
            cur.execute(f'SELECT id FROM "{table_name}" FOR UPDATE')
            cur.fetchall()
            cur.execute(
                f'SELECT COUNT(*), COALESCE(MAX(id), 0) '
                f'FROM "{table_name}"',
            )
            revision_row = cur.fetchone()
            revision = (
                tuple(revision_row.values()) if isinstance(revision_row, dict)
                else tuple(revision_row)
            )
            if expected_revision is not None and tuple(expected_revision) != revision:
                raise ValueError('The citation dataset changed after preview')
            placeholders = ', '.join(['%s'] * len(ids))
            cur.execute(
                f'DELETE FROM "{table_name}" WHERE id IN ({placeholders})', tuple(
                    ids,
                ),
            )
            deleted = cur.rowcount or 0
            if sr_id:
                cur.execute(
                    f'DELETE FROM citation_identities WHERE sr_id = %s AND citation_table_name = %s AND citation_id IN ({placeholders})',
                    (sr_id, table_name, *ids),
                )
            new_revision = self._dataset_revision(cur, table_name)
            conn.commit()
            return {'deleted_count': deleted, 'dataset_revision': new_revision}
        except Exception:
            _safe_rollback(conn)
            raise

    def clear_columns_by_prefix(self, citation_id: int, prefixes: list[str], table_name: str = 'citations') -> int:
        """Set all columns matching any prefix to NULL for a citation."""
        prefixes = [p for p in (prefixes or []) if isinstance(p, str) and p]
        if not prefixes:
            return 0
        cols_meta = self.get_table_columns(table_name)
        cols = []
        for m in cols_meta:
            n = m.get('column_name')
            if not n:
                continue
            for p in prefixes:
                if n.startswith(p):
                    cols.append(n)
                    break
        return self.clear_columns(citation_id, cols, table_name=table_name)

    def copy_jsonb_if_empty(
        self,
        citation_id: int,
        src_col: str,
        dst_col: str,
        dst_value: Any,
        table_name: str = 'citations',
    ) -> int:
        """If dst_col is NULL, set it to dst_value. Returns rows updated (0/1).

        Intended for auto-filling human_* from llm_* while never overwriting.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            # Ensure destination column exists as JSONB
            try:
                cur.execute(
                    f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{dst_col}" JSONB',
                )
            except Exception:
                try:
                    cur.execute(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{dst_col}" JSONB',
                    )
                except Exception:
                    pass

            cur.execute(
                f'UPDATE "{table_name}" SET "{dst_col}" = %s WHERE id = %s AND "{dst_col}" IS NULL',
                (json.dumps(dst_value), int(citation_id)),
            )
            rows = cur.rowcount
            conn.commit()
            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    # -----------------------
    # Citation row helpers
    # -----------------------
    def dump_citations_csv(self, table_name: str = 'citations') -> bytes:
        """Dump the entire `citations` table as CSV bytes.

        Intended to be called from async FastAPI routes via
        `fastapi.concurrency.run_in_threadpool`.

        Uses Postgres COPY for correctness and performance.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            buf = io.StringIO()

            # Order by id for stable exports.
            cur.copy_expert(
                f'COPY (SELECT * FROM "{table_name}" ORDER BY id) TO STDOUT WITH CSV HEADER',
                buf,
            )
            csv_text = buf.getvalue()

            return csv_text.encode('utf-8')
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def dump_citations_csv_filtered(self, table_name: str = 'citations') -> bytes:
        """Dump a filtered CSV suitable for validation.

        Rules:
        - Exclude fulltext* + table/figure artifacts (DI/Grobid) columns.
        - For JSONB columns (llm_*, human_*, llm_param_*, human_param_*), flatten into
          explicit scalar columns (selected/explanation/confidence/found/value/...).
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()

        # 1) Determine columns to export
        cols_meta = self.get_table_columns(table_name)
        exclude_prefixes = ('fulltext',)
        exclude_exact = {'fulltext_url'}
        exclude_contains = ('_coords', '_pages', '_figures', '_tables')

        base_cols: list[str] = []
        jsonb_cols: list[str] = []

        for m in cols_meta:
            col = m.get('column_name')
            if not col:
                continue
            low = col.lower()
            if low in exclude_exact:
                continue
            if any(low.startswith(p) for p in exclude_prefixes):
                continue
            if any(x in low for x in exclude_contains) and low.startswith('fulltext'):
                continue

            is_jsonb = (m.get('udt_name') == 'jsonb') or (
                m.get('data_type') == 'jsonb'
            )
            if is_jsonb:
                jsonb_cols.append(col)
            else:
                base_cols.append(col)

        # 2) Read rows
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            select_cols = base_cols + jsonb_cols
            select_sql = ', '.join(
                [f'"{c}"' for c in select_cols],
            ) if select_cols else '*'
            cur.execute(f'SELECT {select_sql} FROM "{table_name}" ORDER BY id')
            rows = cur.fetchall() or []

            # 3) Build output header
            # Base columns are written as-is
            out_cols: list[str] = list(base_cols)

            # Flatten known json shapes
            def _flatten_keys_for(col: str) -> list[str]:
                # Params — check BEFORE generic llm_/human_ to avoid prefix collision
                # (llm_param_* starts with llm_; human_param_* starts with human_)
                if col.startswith('llm_param_') or col.startswith('human_param_'):
                    return [
                        f"{col}__found",
                        f"{col}__value",
                        f"{col}__explanation",
                        f"{col}__evidence_sentences",
                        f"{col}__evidence_tables",
                        f"{col}__evidence_figures",
                        f"{col}__autofilled",
                        f"{col}__source",
                        f"{col}__timestamp",
                        f"{col}__reviewer",
                    ]
                # Screening
                if col.startswith('llm_') or col.startswith('human_'):
                    return [
                        f"{col}__selected",
                        f"{col}__explanation",
                        f"{col}__confidence",
                        f"{col}__evidence_sentences",
                        f"{col}__evidence_tables",
                        f"{col}__evidence_figures",
                        f"{col}__autofilled",
                        f"{col}__source",
                        f"{col}__timestamp",
                        f"{col}__reviewer",
                    ]
                # Fallback
                return [f"{col}__json"]

            json_flat_cols: dict[str, list[str]] = {
                c: _flatten_keys_for(c) for c in jsonb_cols
            }
            for c in jsonb_cols:
                out_cols.extend(json_flat_cols[c])

            # 4) Normalize JSONB values and emit CSV
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf, fieldnames=out_cols, extrasaction='ignore',
            )
            writer.writeheader()

            def _parse_jsonb(v: Any) -> Any:
                if v is None:
                    return None
                if isinstance(v, (dict, list)):
                    return v
                if isinstance(v, str):
                    s = v.strip()
                    if s.startswith('{') or s.startswith('['):
                        try:
                            return json.loads(s)
                        except Exception:
                            return v
                return v

            def _as_str(v: Any) -> str:
                if v is None:
                    return ''
                if isinstance(v, bool):
                    return 'true' if v else 'false'
                if isinstance(v, (int, float)):
                    return str(v)
                if isinstance(v, (dict, list)):
                    try:
                        return json.dumps(v, ensure_ascii=False)
                    except Exception:
                        return str(v)
                return str(v)

            for r in rows:
                out: dict[str, Any] = {}
                # base
                for c in base_cols:
                    out[c] = _as_str(r.get(c))

                # flatten json
                for c in jsonb_cols:
                    parsed = _parse_jsonb(r.get(c))
                    if not isinstance(parsed, dict):
                        out[f"{c}__json"] = _as_str(parsed)
                        continue

                    # Common fields
                    if c.startswith('llm_param_') or c.startswith('human_param_'):
                        out[f"{c}__found"] = _as_str(parsed.get('found'))
                        out[f"{c}__value"] = _as_str(parsed.get('value'))
                    else:
                        out[f"{c}__selected"] = _as_str(parsed.get('selected'))
                        out[f"{c}__confidence"] = _as_str(
                            parsed.get('confidence'),
                        )

                    out[f"{c}__explanation"] = _as_str(
                        parsed.get('explanation'),
                    )
                    out[f"{c}__evidence_sentences"] = _as_str(
                        parsed.get('evidence_sentences'),
                    )
                    out[f"{c}__evidence_tables"] = _as_str(
                        parsed.get('evidence_tables'),
                    )
                    out[f"{c}__evidence_figures"] = _as_str(
                        parsed.get('evidence_figures'),
                    )
                    out[f"{c}__autofilled"] = _as_str(parsed.get('autofilled'))
                    out[f"{c}__source"] = _as_str(parsed.get('source'))
                    out[f"{c}__timestamp"] = _as_str(parsed.get('timestamp'))
                    out[f"{c}__reviewer"] = _as_str(parsed.get('reviewer'))

                writer.writerow(out)

            return buf.getvalue().encode('utf-8')
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def get_citation_by_id(self, citation_id: int, table_name: str = 'citations') -> dict[str, Any] | None:
        """
        Return a dict mapping column -> value for the citation row, or None.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            try:
                cur = conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
            except Exception:
                cur = conn.cursor()
            cur.execute(
                f'SELECT * FROM "{table_name}" WHERE id = %s', (citation_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if isinstance(row, dict):
                result = row
            else:
                cols = [desc[0] for desc in cur.description]
                result = {cols[i]: row[i] for i in range(len(cols))}

            return result
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def get_citations_by_ids(
        self,
        citation_ids: list[int],
        table_name: str = 'citations',
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch multiple citation rows in one query.

        Args:
            citation_ids: list of ids to fetch
            table_name: screening table name
            fields: optional list of columns to return. If None, returns all columns.

        Returns:
            List[dict] rows. Missing ids are omitted.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        ids: list[int] = []
        for i in citation_ids or []:
            try:
                ids.append(int(i))
            except Exception:
                continue
        if not ids:
            return []

        conn = None
        try:
            conn = postgres_server.conn

            # Optional field selection (defensive): only allow existing columns
            select_sql = '*'
            if fields:
                try:
                    existing_cols = {
                        c.get('column_name')
                        for c in self.get_table_columns(table_name)
                    }
                except Exception:
                    existing_cols = set()
                safe_fields = [
                    f for f in fields if isinstance(
                        f, str,
                    ) and f in existing_cols
                ]
                if safe_fields:
                    select_sql = ', '.join([f'"{c}"' for c in safe_fields])

            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Preserve input ordering as much as possible for stable paging.
            # (We still ORDER BY id, which is fine for our UI; if we need strict
            # input order later we can use array_position.)
            cur.execute(
                f'SELECT {select_sql} FROM "{table_name}" WHERE id = ANY(%s) ORDER BY id',
                (ids,),
            )
            rows = cur.fetchall() or []
            return [dict(r) for r in rows if r]
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def fetch_export_rows(
        self,
        table_name: str,
        columns: list[str],
        scope_kind: str = 'all',
        citation_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch allowlisted citation columns for a validated export scope.

        The export service derives ``columns`` from live table metadata. This
        method validates them again at the database boundary and always selects
        ``id`` so citation-id ownership can be checked before returning a file.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        existing = {
            str(column.get('column_name'))
            for column in self.get_table_columns(table_name)
            if column.get('column_name')
        }
        requested = list(dict.fromkeys(['id', *columns]))
        if any(column not in existing for column in requested):
            raise ValueError(
                'Export contains a column that is not present in the citation table',
            )

        predicates: dict[str, tuple[str, tuple[Any, ...]]] = {
            'all': ('', ()),
            'l1_included': (" WHERE COALESCE(human_l1_decision, '') = 'include'", ()),
            'l2_included': (" WHERE COALESCE(human_l2_decision, '') = 'include'", ()),
            'citation_ids': (' WHERE id = ANY(%s)', (citation_ids or [],)),
        }
        if scope_kind not in predicates:
            raise ValueError(f'Unsupported export row scope: {scope_kind}')
        if scope_kind in ('l1_included', 'l2_included'):
            decision_column = f"human_{scope_kind.removesuffix('_included')}_decision"
            if decision_column not in existing:
                return []

        where_sql, params = predicates[scope_kind]
        select_sql = ', '.join(f'"{column}"' for column in requested)
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                f'SELECT {select_sql} FROM "{table_name}"{where_sql} ORDER BY id',
                params,
            )
            return [dict(row) for row in (cur.fetchall() or []) if row]
        except Exception:
            _safe_rollback(conn)
            raise

    def backfill_human_decisions(self, criteria_parsed: dict[str, Any], table_name: str = 'citations') -> int:
        """Recompute and persist human_l1_decision / human_l2_decision for all rows.

        This is used to ensure decision columns are never stale when the UI fetches
        filtered citation id lists.

        Rules:
        - include: all questions answered and no selected contains "exclude"
        - exclude: any selected contains "exclude"
        - undecided: any question missing/unanswered
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()

        # Local import avoids a module cycle: the eligibility service owns the
        # domain rule while this repository owns persistence.
        from .screening_eligibility_service import compute_screening_decisions

        cp = criteria_parsed or {}
        l1_qs = (cp.get('l1') or {}).get(
            'questions',
        ) if isinstance(cp.get('l1'), dict) else None
        l2_qs = (cp.get('l2') or {}).get(
            'questions',
        ) if isinstance(cp.get('l2'), dict) else None
        l1_qs = l1_qs if isinstance(l1_qs, list) else []
        l2_qs = l2_qs if isinstance(l2_qs, list) else []

        # IMPORTANT: human_l2_decision is used as the Extract filter.
        # It must represent "passed to L2/extract" and therefore consider BOTH
        # the original L1 criteria questions and any L2 full-text criteria questions.
        l2_union_qs = list(l1_qs) + list(l2_qs)

        # Ensure decision columns exist
        self.create_column('human_l1_decision', 'TEXT', table_name=table_name)
        self.create_column('human_l2_decision', 'TEXT', table_name=table_name)

        def _human_col(q: str, stage: str) -> str:
            core = snake_case(q, max_len=56)
            return f"human_{stage}_{core}" if core else 'human_col'

        def _llm_col(q: str, stage: str) -> str:
            core = snake_case(q, max_len=56)
            return f"llm_{stage}_{core}" if core else 'llm_col'

        needed_cols: list[str] = []
        for q in l1_qs:
            if not isinstance(q, str) or not q.strip():
                continue
            needed_cols.extend((
                _human_col(q, 'l1'), _llm_col(
                    q, 'l1',
                ), f'llm_{snake_case(q, max_len=56)}',
            ))
        for q in l2_qs:
            if not isinstance(q, str) or not q.strip():
                continue
            needed_cols.extend((
                _human_col(q, 'l2'), _llm_col(
                    q, 'l2',
                ), f'llm_{snake_case(q, max_len=56)}',
            ))
        # stable unique
        seen = set()
        uniq_cols = []
        for c in needed_cols:
            if c not in seen:
                seen.add(c)
                uniq_cols.append(c)

        # Only select columns that actually exist.
        # If we try to SELECT a non-existent human_* column, the query fails and the
        # caller silently skips the backfill, leaving stale decision columns.
        try:
            existing_cols = {
                c.get('column_name')
                for c in self.get_table_columns(table_name)
            }
        except Exception:
            existing_cols = set()

        existing_answer_cols = [c for c in uniq_cols if c in existing_cols]

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            select_cols = ['id'] + existing_answer_cols
            sql_cols = ', '.join([f'"{c}"' for c in select_cols])
            cur.execute(f'SELECT {sql_cols} FROM "{table_name}" ORDER BY id')
            rows = cur.fetchall() or []

            updates: list[tuple[str, str, int]] = []
            for r in rows:
                if not r:
                    continue
                rid = r.get('id')
                try:
                    rid_i = int(rid)
                except Exception:
                    continue
                d1, d2 = compute_screening_decisions(r, cp)
                updates.append((d1, d2, rid_i))

            if not updates:
                return 0

            cur2 = conn.cursor()
            psycopg2.extras.execute_batch(
                cur2,
                f'UPDATE "{table_name}" SET human_l1_decision = %s, human_l2_decision = %s WHERE id = %s',
                updates,
            )
            conn.commit()
            return len(updates)
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def list_citation_ids(self, filter_step=None, table_name: str = 'citations') -> list[int]:
        """
        Return list of integer primary keys (id) from citations table ordered by id.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()

            if filter_step is None or str(filter_step).strip() == '':
                query = f'SELECT id FROM "{table_name}" ORDER BY id'
                cur.execute(query)
            else:
                step = str(filter_step).strip().lower()
                if step == 'l1':
                    # Validation rule (B1/B2): Full-text list is driven by the human L1 decision.
                    # Do NOT use l1_screen/l2_screen booleans.
                    try:
                        cur.execute(
                            f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "human_l1_decision" TEXT',
                        )
                    except Exception:
                        pass
                    cur.execute(
                        f"SELECT id FROM \"{table_name}\" WHERE COALESCE(human_l1_decision, '') = 'include' ORDER BY id",
                    )
                elif step == 'l2':
                    # Validation rule (B1/B2): Extract list is driven by the human L2 decision.
                    try:
                        cur.execute(
                            f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "human_l2_decision" TEXT',
                        )
                    except Exception:
                        pass
                    cur.execute(
                        f"SELECT id FROM \"{table_name}\" WHERE COALESCE(human_l2_decision, '') = 'include' ORDER BY id",
                    )
                else:
                    cur.execute(f'SELECT id FROM "{table_name}" ORDER BY id')

            rows = cur.fetchall()

            return [int(r[0]) for r in rows]
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def list_fulltext_urls(self, table_name: str = 'citations') -> list[str]:
        """
        Return list of fulltext_url values (non-null) from citations table.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                f'SELECT fulltext_url FROM "{table_name}" WHERE fulltext_url IS NOT NULL',
            )
            rows = cur.fetchall()

            return [r[0] for r in rows if r and r[0]]
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def update_citation_fulltext(self, citation_id: int, fulltext_path: str) -> int:
        """
        Backwards-compatible helper used by some routers. Sets `fulltext_url`.
        """
        return self.update_text_column(citation_id, 'fulltext_url', fulltext_path)

    # -----------------------
    # Upload fulltext and compute md5
    # -----------------------
    def attach_fulltext(
        self,
        citation_id: int,
        azure_path: str,
        file_bytes: bytes,
        table_name: str = 'citations',
    ) -> int:
        """
        Set the fulltext_url for the given citation.
        Creates columns if necessary. Returns rows modified (0/1).
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        # create columns if missing
        self.create_column('fulltext_url', 'TEXT', table_name=table_name)
        # compute md5
        md5 = hashlib.md5(file_bytes).hexdigest(
        ) if file_bytes is not None else ''

        # create md5 column if missing
        self.create_column('fulltext_md5', 'TEXT', table_name=table_name)

        # update both columns
        conn = postgres_server.conn
        try:
            cur = conn.cursor()
            cur.execute(
                f'UPDATE "{table_name}" SET "fulltext_url" = %s, "fulltext_md5" = %s WHERE id = %s',
                (azure_path, md5, int(citation_id)),
            )
            rows = cur.rowcount
            conn.commit()
            return rows
        except Exception:
            _safe_rollback(conn)
            raise

    def attach_fulltext_atomic(
        self,
        citation_id: int,
        azure_path: str,
        file_md5: str,
        *,
        source: str,
        source_url: str | None = None,
        replace: bool = False,
        table_name: str = 'citations',
    ) -> dict[str, Any]:
        """Lock, re-check, and atomically attach a staged full-text document."""
        table_name = _validate_ident(table_name, kind='table_name')
        self.ensure_pdf_linkage_columns(table_name)
        self.create_column('fulltext_url', 'TEXT', table_name=table_name)
        self.create_column('fulltext_md5', 'TEXT', table_name=table_name)
        conn = postgres_server.conn
        try:
            cur = conn.cursor()
            cur.execute(
                f'''SELECT fulltext_url, fulltext_md5 FROM "{table_name}"
                    WHERE id=%s FOR UPDATE''',
                (int(citation_id),),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return {'attached': False, 'reason': 'citation_not_found'}
            old_url, old_md5 = row[0] or '', row[1] or ''
            if old_url and not replace:
                conn.rollback()
                return {
                    'attached': False,
                    'reason': 'concurrent_fulltext',
                    'old_url': old_url,
                }
            changed = bool(old_url and (not old_md5 or old_md5 != file_md5))
            if changed:
                # Derived full-text artifacts and extraction outputs cannot be
                # retained when manual replacement changes the source PDF.
                cur.execute(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema='public' AND table_name=%s
                         AND (column_name IN (
                           'fulltext','fulltext_coords','fulltext_pages',
                           'fulltext_figures','fulltext_tables',
                           'llm_l2_decision','human_l2_decision'
                         ) OR column_name LIKE 'llm_param_%%'
                            OR column_name LIKE 'human_param_%%')""",
                    (table_name,),
                )
                clear_columns = [
                    str(item[0])
                    for item in (cur.fetchall() or [])
                ]
                if clear_columns:
                    assignments = ', '.join(
                        f'"{name}"=NULL' for name in clear_columns
                    )
                    cur.execute(
                        f'UPDATE "{table_name}" SET {assignments} WHERE id=%s',
                        (int(citation_id),),
                    )
            cur.execute(
                f'''UPDATE "{table_name}" SET
                    fulltext_url=%s, fulltext_md5=%s,
                    pdf_link_status='linked', pdf_link_reason=NULL,
                    pdf_link_source=%s, pdf_link_url=%s,
                    pdf_link_error=NULL, pdf_link_last_checked_at=now()
                    WHERE id=%s''',
                (azure_path, file_md5, source, source_url, int(citation_id)),
            )
            conn.commit()
            return {
                'attached': True,
                'reason': 'linked',
                'old_url': old_url or None,
                'changed': changed,
            }
        except Exception:
            _safe_rollback(conn)
            raise

    def ensure_pdf_linkage_columns(self, table_name: str = 'citations') -> None:
        """Apply the idempotent PDF-linkage schema to a dynamic citation table."""
        table_name = _validate_ident(table_name, kind='table_name')
        for name, data_type in (
            ('pdf_link_status', 'TEXT'),
            ('pdf_link_reason', 'TEXT'),
            ('pdf_link_source', 'TEXT'),
            ('pdf_link_url', 'TEXT'),
            ('pdf_link_last_checked_at', 'TIMESTAMPTZ'),
            ('pdf_link_error', 'TEXT'),
            ('pdf_link_doi_source', 'TEXT'),
        ):
            self.create_column(name, data_type, table_name=table_name)

    def save_recovered_doi(
        self, citation_id: int, doi: str, *, source: str,
        table_name: str = 'citations',
    ) -> bool:
        """Persist a recovered DOI without overwriting DOI data written concurrently."""
        table_name = _validate_ident(table_name, kind='table_name')
        self.ensure_pdf_linkage_columns(table_name)
        self.create_column('doi', 'TEXT', table_name=table_name)
        conn = postgres_server.conn
        try:
            cur = conn.cursor()
            cur.execute(
                f'''UPDATE "{table_name}" SET doi=%s, pdf_link_doi_source=%s
                    WHERE id=%s AND NULLIF(BTRIM(doi), '') IS NULL''',
                (doi, source, int(citation_id)),
            )
            changed = bool(cur.rowcount)
            conn.commit()
            return changed
        except Exception:
            _safe_rollback(conn)
            raise

    def list_pdf_linkage_ids(self, table_name: str = 'citations') -> list[int]:
        table_name = _validate_ident(table_name, kind='table_name')
        self.ensure_pdf_linkage_columns(table_name)
        self.create_column('human_l1_decision', 'TEXT', table_name=table_name)
        conn = postgres_server.conn
        try:
            cur = conn.cursor()
            cur.execute(
                f'''SELECT id FROM "{table_name}"
                    WHERE COALESCE(fulltext_url, '') = ''
                      AND COALESCE(human_l1_decision, '') = 'include'
                    ORDER BY id''',
            )
            return [int(row[0]) for row in (cur.fetchall() or [])]
        except Exception:
            _safe_rollback(conn)
            raise

    def update_pdf_linkage_outcome(
        self,
        citation_id: int,
        *,
        status: str,
        reason: str | None = None,
        source: str | None = None,
        url: str | None = None,
        error: str | None = None,
        table_name: str = 'citations',
    ) -> int:
        table_name = _validate_ident(table_name, kind='table_name')
        self.ensure_pdf_linkage_columns(table_name)
        conn = postgres_server.conn
        try:
            cur = conn.cursor()
            cur.execute(
                f'''UPDATE "{table_name}" SET
                    pdf_link_status=%s, pdf_link_reason=%s, pdf_link_source=%s,
                    pdf_link_url=%s, pdf_link_error=%s,
                    pdf_link_last_checked_at=now() WHERE id=%s''',
                (
                    status, reason, source, url, (error or '')
                    [:2000] or None, int(citation_id),
                ),
            )
            rows = cur.rowcount
            conn.commit()
            return rows
        except Exception:
            _safe_rollback(conn)
            raise

    # -----------------------
    # Column get/set helpers
    # -----------------------
    def get_column_value(self, citation_id: int, column: str, table_name: str = 'citations') -> Any:
        """
        Return the value stored in `column` for the citation row (or None).
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            try:
                cur = conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
            except Exception:
                cur = conn.cursor()
            cur.execute(
                f'SELECT "{column}" FROM "{table_name}" WHERE id = %s', (
                    citation_id,
                ),
            )
            row = cur.fetchone()
            if not row:
                return None
            # row may be dict or tuple
            if isinstance(row, dict):
                val = list(row.values())[0] if row else None
            else:
                val = row[0] if row and len(row) > 0 else None

            return val
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def set_column_value(self, citation_id: int, column: str, value: Any, table_name: str = 'citations') -> int:
        """
        Generic setter for a citation row column. Will create a TEXT column if it doesn't exist.
        """
        # For simplicity, create a TEXT column. Callers that need JSONB should use update_jsonb_column.
        self.create_column(column, 'TEXT', table_name=table_name)
        return self.update_text_column(citation_id, column, value if value is not None else None, table_name=table_name)

    # -----------------------
    # Per-upload table lifecycle helpers
    # -----------------------
    def drop_table(self, table_name: str, cascade: bool = True) -> None:
        """Drop a screening table in the shared database."""
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cas = ' CASCADE' if cascade else ''
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}"{cas}')
            conn.commit()
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def create_table_and_insert_sync(
        self,
        table_name: str,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> int:
        """Blocking function to create a screening table and insert rows.

        Table schema mirrors the old per-database implementation, but the table name
        is per-upload (e.g. sr_<sr>_<ts>_citations) inside the shared DB.
        """
        table_name = _validate_ident(table_name, kind='table_name')
        self._require_psycopg2()
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()

            # Create table
            col_defs = []
            for col in columns:
                safe = snake_case(col)
                col_defs.append(f'"{safe}" TEXT')

            col_defs.append('"cit_id" TEXT')
            col_defs.append('"fulltext_url" TEXT')
            col_defs.append('"fulltext" TEXT')
            col_defs.append('"fulltext_md5" TEXT')
            col_defs.append('"pdf_link_status" TEXT')
            col_defs.append('"pdf_link_reason" TEXT')
            col_defs.append('"pdf_link_source" TEXT')
            col_defs.append('"pdf_link_url" TEXT')
            col_defs.append(
                '"pdf_link_last_checked_at" TIMESTAMP WITH TIME ZONE',
            )
            col_defs.append('"pdf_link_error" TEXT')
            col_defs.append('"pdf_link_doi_source" TEXT')

            # Step-level validation fields (agentic screening plan)
            col_defs.append('"l1_validated_by" TEXT')
            col_defs.append('"l1_validated_at" TIMESTAMP WITH TIME ZONE')
            col_defs.append('"l2_validated_by" TEXT')
            col_defs.append('"l2_validated_at" TIMESTAMP WITH TIME ZONE')
            col_defs.append('"parameters_validated_by" TEXT')
            col_defs.append(
                '"parameters_validated_at" TIMESTAMP WITH TIME ZONE',
            )

            col_defs.append(
                '"created_at" TIMESTAMP WITH TIME ZONE DEFAULT now()',
            )

            cols_sql = ', '.join(col_defs)
            create_table_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (id SERIAL PRIMARY KEY, {cols_sql})'
            cur.execute(create_table_sql)

            # Insert rows
            inserted = 0
            if rows:
                safe_cols = [snake_case(c) for c in columns]
                insert_cols = [f'"{c}"' for c in safe_cols] + [
                    '"cit_id"',
                    '"fulltext_url"', '"fulltext"', '"fulltext_md5"',
                ]
                placeholders = ', '.join(['%s'] * len(insert_cols))
                insert_sql = f'INSERT INTO "{table_name}" ({", ".join(insert_cols)}) VALUES ({placeholders})'

                def _row_has_data(row: dict) -> bool:
                    for orig_col in columns:
                        v = row.get(orig_col)
                        if isinstance(v, str) and v.strip() != '':
                            return True
                    return False

                filtered_rows = [r for r in rows if _row_has_data(r)]

                values = []
                for r in filtered_rows:
                    row_vals = [
                        r.get(orig_col) if r.get(
                            orig_col,
                        ) is not None else None for orig_col in columns
                    ]
                    row_vals.append(
                        r.get('cit_id') if r.get(
                            'cit_id',
                        ) is not None else None,
                    )
                    row_vals.append(
                        r.get('fulltext_url') if r.get(
                            'fulltext_url',
                        ) is not None else None,
                    )
                    row_vals.append(
                        r.get('fulltext') if r.get(
                            'fulltext',
                        ) is not None else None,
                    )
                    row_vals.append(
                        r.get('fulltext_md5') if r.get(
                            'fulltext_md5',
                        ) is not None else None,
                    )
                    values.append(tuple(row_vals))

                if values:
                    psycopg2.extras.execute_batch(cur, insert_sql, values)
                    inserted = len(values)

            conn.commit()

            return inserted
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    # NOTE: legacy per-database helpers (drop_database, create_db_and_table_sync) were
    # intentionally removed in favor of per-upload tables in a shared database.

    def load_include_columns_from_criteria(self, sr_doc: dict[str, Any] | None = None) -> list[str]:
        """
        Load every configured citation field for L1 screening.

        The v2 schema stores these in citation_fields.l1_include. Legacy criteria
        store them in l1.include or at the top level under include. In particular,
        do not reduce retrospective-study uploads to title/abstract: every selected
        CSV field is part of the screening context.
        """
        # 1) try SR-specific parsed criteria
        try:
            if sr_doc and isinstance(sr_doc, dict):
                cp = sr_doc.get('criteria_parsed') or sr_doc.get('criteria')
                if cp and isinstance(cp, dict):
                    citation_fields = cp.get('citation_fields')
                    if isinstance(citation_fields, dict):
                        inc_fields = citation_fields.get('l1_include')
                        if isinstance(inc_fields, list) and inc_fields:
                            return inc_fields
                    if 'l1' in cp and isinstance(cp.get('l1'), dict):
                        inc = cp.get('l1', {}).get('include')
                        if isinstance(inc, list) and inc:
                            return inc
                    inc2 = cp.get('include') if isinstance(cp, dict) else None
                    if isinstance(inc2, list) and inc2:
                        return inc2
        except Exception:
            pass

        # 2) fallback to project file
        cfg_path = os.path.join(
            os.path.dirname(
                __file__,
            ), '..', 'sr_setup', 'configs', 'criteria_config_measles_updated.yaml',
        )
        cfg_path = os.path.normpath(cfg_path)
        try:
            import yaml

            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
                include = cfg.get('include', [])
                if not isinstance(include, list):
                    return []
                return include
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def build_combined_citation_from_row(self, row: dict[str, Any], include_columns: list[str]) -> str:
        parts: list[str] = []
        if not row:
            return ''
        for col in include_columns:
            val = resolve_source_value(row, col)
            if val is None:
                continue
            parts.append(f"{col}: {val}  \n")
        return ''.join(parts)


# module-level instance
cits_dp_service = CitsDPService()
