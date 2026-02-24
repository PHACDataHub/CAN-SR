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
from typing import Any, Dict, List, Optional, Tuple
import psycopg2
import psycopg2.extras
import json
import re
import os
import io
import csv
import urllib.parse as up
import hashlib

# Local settings import (for POSTGRES_ADMIN_DSN / DATABASE_URL usage)
try:
    from ..core.config import settings
except Exception:
    settings = None

from .postgres_auth import postgres_server


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


# -----------------------
# Basic column helpers
# -----------------------
def snake_case(name: str, max_len: int = 63) -> str:
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"[^\w]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if re.match(r"^\d", s):
        s = f"c_{s}"
    return s[:max_len]


def snake_case_param(name: str) -> str:
    core = snake_case(name, max_len=52)
    col = f"llm_param_{core}" if core else "llm_param_param"
    return col[:60]


def snake_case_column(name: str) -> str:
    core = snake_case(name, max_len=56)
    col = f"llm_{core}" if core else "llm_col"
    return col[:60]


# -----------------------
# Identifier helpers
# -----------------------
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _validate_ident(name: str, kind: str = "identifier") -> str:
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
def parse_dsn(dsn: str) -> Dict[str, str]:
    """
    Extract host/port/user/password metadata from a libpq DSN or URL.
    """
    result: Dict[str, str] = {}
    try:
        if "=" in (dsn or "") and "://" not in (dsn or ""):
            parts = dsn.split()
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    result[k] = v
        else:
            parsed = up.urlparse(dsn)
            result["host"] = parsed.hostname or ""
            result["port"] = str(parsed.port) if parsed.port else ""
            result["user"] = parsed.username or ""
            result["password"] = parsed.password or ""
    except Exception:
        pass
    return result


def _construct_db_dsn_from_admin(admin_dsn: str, db_name: str) -> str:
    """
    Given an admin DSN (URL or key=value string), return a DSN pointing to db_name.
    """
    if "://" in (admin_dsn or ""):
        parsed = up.urlparse(admin_dsn)
        new_path = "/" + db_name
        new_parsed = parsed._replace(path=new_path)
        return up.urlunparse(new_parsed)
    else:
        if "dbname=" in (admin_dsn or ""):
            return re.sub(r"dbname=[^ ]+", f"dbname={db_name}", admin_dsn)
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

    # -----------------------
    # Low level connection helpers
    # -----------------------


    # -----------------------
    # Generic column ops
    # -----------------------
    def create_column(self, col: str, col_type: str, table_name: str = "citations") -> None:
        """
        Create column on citations table if it doesn't already exist.
        col should be the exact column name to use (caller may pass snake_case(col)).
        col_type is the SQL type (e.g. TEXT, JSONB).
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" {col_type}')
            except Exception:
                # fallback for PG versions without IF NOT EXISTS
                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {col_type}')
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
        table_name: str = "citations",
    ) -> int:
        """
        Update a JSONB column for a citation. Creates the column if needed.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" JSONB')
            except Exception:
                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" JSONB')
                except Exception:
                    pass
            cur.execute(f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (json.dumps(data), int(citation_id)))
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
        table_name: str = "citations",
    ) -> int:
        """
        Update a TEXT column for a citation. Creates the column if needed.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" TEXT')
            except Exception:
                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT')
                except Exception:
                    pass
            cur.execute(f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (text_value, int(citation_id)))
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
        table_name: str = "citations",
    ) -> int:
        """Update a BOOLEAN column for a citation. Creates the column if needed."""
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            try:
                cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" BOOLEAN')
            except Exception:
                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" BOOLEAN')
                except Exception:
                    pass
            cur.execute(f'UPDATE "{table_name}" SET "{col}" = %s WHERE id = %s', (bool(bool_value), int(citation_id)))
            rows = cur.rowcount
            conn.commit()
            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def get_table_columns(self, table_name: str = "citations") -> List[Dict[str, str]]:
        """Return [{name, data_type, udt_name}] for table columns ordered by ordinal_position."""
        table_name = _validate_ident(table_name, kind="table_name")
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
                    "column_name": str(r.get("column_name")),
                    "data_type": str(r.get("data_type")),
                    "udt_name": str(r.get("udt_name")),
                }
                for r in rows
                if r and r.get("column_name")
            ]
        finally:
            if conn:
                pass

    def clear_columns(self, citation_id: int, columns: List[str], table_name: str = "citations") -> int:
        """Set provided columns to NULL for a citation. Ignores unknown columns."""
        table_name = _validate_ident(table_name, kind="table_name")
        if not columns:
            return 0
        conn = None
        try:
            # filter to real columns
            existing = {c["column_name"] for c in self.get_table_columns(table_name)}
            cols = [c for c in columns if c in existing]
            if not cols:
                return 0

            conn = postgres_server.conn
            cur = conn.cursor()
            set_sql = ", ".join([f'"{c}" = NULL' for c in cols])
            cur.execute(f'UPDATE "{table_name}" SET {set_sql} WHERE id = %s', (int(citation_id),))
            rows = cur.rowcount
            conn.commit()
            return rows or 0
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def clear_columns_by_prefix(self, citation_id: int, prefixes: List[str], table_name: str = "citations") -> int:
        """Set all columns matching any prefix to NULL for a citation."""
        prefixes = [p for p in (prefixes or []) if isinstance(p, str) and p]
        if not prefixes:
            return 0
        cols_meta = self.get_table_columns(table_name)
        cols = []
        for m in cols_meta:
            n = m.get("column_name")
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
        table_name: str = "citations",
    ) -> int:
        """If dst_col is NULL, set it to dst_value. Returns rows updated (0/1).

        Intended for auto-filling human_* from llm_* while never overwriting.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            # Ensure destination column exists as JSONB
            try:
                cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{dst_col}" JSONB')
            except Exception:
                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{dst_col}" JSONB')
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
    def dump_citations_csv(self, table_name: str = "citations") -> bytes:
        """Dump the entire `citations` table as CSV bytes.

        Intended to be called from async FastAPI routes via
        `fastapi.concurrency.run_in_threadpool`.

        Uses Postgres COPY for correctness and performance.
        """
        table_name = _validate_ident(table_name, kind="table_name")
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



            return csv_text.encode("utf-8")
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def dump_citations_csv_filtered(self, table_name: str = "citations") -> bytes:
        """Dump a filtered CSV suitable for validation.

        Rules:
        - Exclude fulltext* + table/figure artifacts (DI/Grobid) columns.
        - For JSONB columns (llm_*, human_*, llm_param_*, human_param_*), flatten into
          explicit scalar columns (selected/explanation/confidence/found/value/...).
        """
        table_name = _validate_ident(table_name, kind="table_name")

        # 1) Determine columns to export
        cols_meta = self.get_table_columns(table_name)
        exclude_prefixes = ("fulltext",)
        exclude_exact = {"fulltext_url"}
        exclude_contains = ("_coords", "_pages", "_figures", "_tables")

        base_cols: List[str] = []
        jsonb_cols: List[str] = []

        for m in cols_meta:
            col = m.get("column_name")
            if not col:
                continue
            low = col.lower()
            if low in exclude_exact:
                continue
            if any(low.startswith(p) for p in exclude_prefixes):
                continue
            if any(x in low for x in exclude_contains) and low.startswith("fulltext"):
                continue

            is_jsonb = (m.get("udt_name") == "jsonb") or (m.get("data_type") == "jsonb")
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
            select_sql = ", ".join([f'"{c}"' for c in select_cols]) if select_cols else "*"
            cur.execute(f'SELECT {select_sql} FROM "{table_name}" ORDER BY id')
            rows = cur.fetchall() or []

            # 3) Build output header
            # Base columns are written as-is
            out_cols: List[str] = list(base_cols)

            # Flatten known json shapes
            def _flatten_keys_for(col: str) -> List[str]:
                # Screening
                if col.startswith("llm_") or col.startswith("human_"):
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
                # Params
                if col.startswith("llm_param_") or col.startswith("human_param_"):
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
                # Fallback
                return [f"{col}__json"]

            json_flat_cols: Dict[str, List[str]] = {c: _flatten_keys_for(c) for c in jsonb_cols}
            for c in jsonb_cols:
                out_cols.extend(json_flat_cols[c])

            # 4) Normalize JSONB values and emit CSV
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=out_cols, extrasaction="ignore")
            writer.writeheader()

            def _parse_jsonb(v: Any) -> Any:
                if v is None:
                    return None
                if isinstance(v, (dict, list)):
                    return v
                if isinstance(v, str):
                    s = v.strip()
                    if s.startswith("{") or s.startswith("["):
                        try:
                            return json.loads(s)
                        except Exception:
                            return v
                return v

            def _as_str(v: Any) -> str:
                if v is None:
                    return ""
                if isinstance(v, bool):
                    return "true" if v else "false"
                if isinstance(v, (int, float)):
                    return str(v)
                if isinstance(v, (dict, list)):
                    try:
                        return json.dumps(v, ensure_ascii=False)
                    except Exception:
                        return str(v)
                return str(v)

            for r in rows:
                out: Dict[str, Any] = {}
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
                    if c.startswith("llm_param_") or c.startswith("human_param_"):
                        out[f"{c}__found"] = _as_str(parsed.get("found"))
                        out[f"{c}__value"] = _as_str(parsed.get("value"))
                    else:
                        out[f"{c}__selected"] = _as_str(parsed.get("selected"))
                        out[f"{c}__confidence"] = _as_str(parsed.get("confidence"))

                    out[f"{c}__explanation"] = _as_str(parsed.get("explanation"))
                    out[f"{c}__evidence_sentences"] = _as_str(parsed.get("evidence_sentences"))
                    out[f"{c}__evidence_tables"] = _as_str(parsed.get("evidence_tables"))
                    out[f"{c}__evidence_figures"] = _as_str(parsed.get("evidence_figures"))
                    out[f"{c}__autofilled"] = _as_str(parsed.get("autofilled"))
                    out[f"{c}__source"] = _as_str(parsed.get("source"))
                    out[f"{c}__timestamp"] = _as_str(parsed.get("timestamp"))
                    out[f"{c}__reviewer"] = _as_str(parsed.get("reviewer"))

                writer.writerow(out)

            return buf.getvalue().encode("utf-8")
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def get_citation_by_id(self, citation_id: int, table_name: str = "citations") -> Optional[Dict[str, Any]]:
        """
        Return a dict mapping column -> value for the citation row, or None.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            except Exception:
                cur = conn.cursor()
            cur.execute(f'SELECT * FROM "{table_name}" WHERE id = %s', (citation_id,))
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

    def backfill_human_decisions(self, criteria_parsed: Dict[str, Any], table_name: str = "citations") -> int:
        """Recompute and persist human_l1_decision / human_l2_decision for all rows.

        This is used to ensure decision columns are never stale when the UI fetches
        filtered citation id lists.

        Rules:
        - include: all questions answered and no selected contains "exclude"
        - exclude: any selected contains "exclude"
        - undecided: any question missing/unanswered
        """
        table_name = _validate_ident(table_name, kind="table_name")

        cp = criteria_parsed or {}
        l1_qs = (cp.get("l1") or {}).get("questions") if isinstance(cp.get("l1"), dict) else None
        l2_qs = (cp.get("l2") or {}).get("questions") if isinstance(cp.get("l2"), dict) else None
        l1_qs = l1_qs if isinstance(l1_qs, list) else []
        l2_qs = l2_qs if isinstance(l2_qs, list) else []

        # IMPORTANT: human_l2_decision is used as the Extract filter.
        # It must represent "passed to L2/extract" and therefore consider BOTH
        # the original L1 criteria questions and any L2 full-text criteria questions.
        l2_union_qs = list(l1_qs) + list(l2_qs)

        # Ensure decision columns exist
        self.create_column("human_l1_decision", "TEXT", table_name=table_name)
        self.create_column("human_l2_decision", "TEXT", table_name=table_name)

        def _human_col(q: str) -> str:
            core = snake_case(q, max_len=56)
            return f"human_{core}" if core else "human_col"

        needed_cols: List[str] = []
        for q in list(l2_union_qs):
            if not isinstance(q, str) or not q.strip():
                continue
            needed_cols.append(_human_col(q))
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
            existing_cols = {c.get("column_name") for c in self.get_table_columns(table_name)}
        except Exception:
            existing_cols = set()

        existing_human_cols = [c for c in uniq_cols if c in existing_cols]

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            select_cols = ["id"] + existing_human_cols
            sql_cols = ", ".join([f'"{c}"' for c in select_cols])
            cur.execute(f'SELECT {sql_cols} FROM "{table_name}" ORDER BY id')
            rows = cur.fetchall() or []

            def _parse_jsonb(v: Any) -> Dict[str, Any]:
                if v is None:
                    return {}
                if isinstance(v, dict):
                    return v
                if isinstance(v, str):
                    s = v.strip()
                    if s.startswith("{"):
                        try:
                            obj = json.loads(s)
                            return obj if isinstance(obj, dict) else {}
                        except Exception:
                            return {}
                return {}

            def _compute(step_qs: List[str], row: Dict[str, Any]) -> str:
                if not step_qs:
                    return "undecided"
                for q in step_qs:
                    col = _human_col(q)
                    # Column not present => no human answer recorded => undecided
                    if col not in existing_cols:
                        return "undecided"
                    hval = row.get(col)
                    if hval is None:
                        return "undecided"
                    hobj = _parse_jsonb(hval)
                    selected = hobj.get("selected")
                    # Treat empty/whitespace as unanswered (UI shows "-- select --")
                    if selected is None or (isinstance(selected, str) and selected.strip() == ""):
                        return "undecided"
                    if "exclude" in str(selected).lower():
                        return "exclude"
                return "include"

            updates: List[Tuple[str, str, int]] = []
            for r in rows:
                if not r:
                    continue
                rid = r.get("id")
                try:
                    rid_i = int(rid)
                except Exception:
                    continue
                d1 = _compute(l1_qs, r)
                d2 = _compute(l2_union_qs, r)
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

    def list_citation_ids(self, filter_step=None, table_name: str = "citations") -> List[int]:
        """
        Return list of integer primary keys (id) from citations table ordered by id.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()

            if filter_step is None or str(filter_step).strip() == "":
                query = f'SELECT id FROM "{table_name}" ORDER BY id'
                cur.execute(query)
            else:
                step = str(filter_step).strip().lower()
                if step == "l1":
                    # Validation rule (B1/B2): Full-text list is driven by the human L1 decision.
                    # Do NOT use l1_screen/l2_screen booleans.
                    try:
                        cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "human_l1_decision" TEXT')
                    except Exception:
                        pass
                    cur.execute(
                        f"SELECT id FROM \"{table_name}\" WHERE COALESCE(human_l1_decision, '') = 'include' ORDER BY id"
                    )
                elif step == "l2":
                    # Validation rule (B1/B2): Extract list is driven by the human L2 decision.
                    try:
                        cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "human_l2_decision" TEXT')
                    except Exception:
                        pass
                    cur.execute(
                        f"SELECT id FROM \"{table_name}\" WHERE COALESCE(human_l2_decision, '') = 'include' ORDER BY id"
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

    def list_fulltext_urls(self, table_name: str = "citations") -> List[str]:
        """
        Return list of fulltext_url values (non-null) from citations table.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(f'SELECT fulltext_url FROM "{table_name}" WHERE fulltext_url IS NOT NULL')
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
        return self.update_text_column(citation_id, "fulltext_url", fulltext_path)

    # -----------------------
    # Upload fulltext and compute md5
    # -----------------------
    def attach_fulltext(
        self,
        citation_id: int,
        azure_path: str,
        file_bytes: bytes,
        table_name: str = "citations",
    ) -> int:
        """
        Set the fulltext_url for the given citation.
        Creates columns if necessary. Returns rows modified (0/1).
        """
        table_name = _validate_ident(table_name, kind="table_name")
        # create columns if missing
        self.create_column("fulltext_url", "TEXT", table_name=table_name)
        # compute md5
        md5 = hashlib.md5(file_bytes).hexdigest() if file_bytes is not None else ""

        # create md5 column if missing
        self.create_column("fulltext_md5", "TEXT", table_name=table_name)

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

    # -----------------------
    # Column get/set helpers
    # -----------------------
    def get_column_value(self, citation_id: int, column: str, table_name: str = "citations") -> Any:
        """
        Return the value stored in `column` for the citation row (or None).
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            except Exception:
                cur = conn.cursor()
            cur.execute(f'SELECT "{column}" FROM "{table_name}" WHERE id = %s', (citation_id,))
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

    def set_column_value(self, citation_id: int, column: str, value: Any, table_name: str = "citations") -> int:
        """
        Generic setter for a citation row column. Will create a TEXT column if it doesn't exist.
        """
        # For simplicity, create a TEXT column. Callers that need JSONB should use update_jsonb_column.
        self.create_column(column, "TEXT", table_name=table_name)
        return self.update_text_column(citation_id, column, value if value is not None else None, table_name=table_name)

    # -----------------------
    # Per-upload table lifecycle helpers
    # -----------------------
    def drop_table(self, table_name: str, cascade: bool = True) -> None:
        """Drop a screening table in the shared database."""
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            conn.autocommit = True
            cur = conn.cursor()
            cas = " CASCADE" if cascade else ""
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}"{cas}')
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            if conn:
                pass

    def create_table_and_insert_sync(
        self,
        table_name: str,
        columns: List[str],
        rows: List[Dict[str, Any]],
    ) -> int:
        """Blocking function to create a screening table and insert rows.

        Table schema mirrors the old per-database implementation, but the table name
        is per-upload (e.g. sr_<sr>_<ts>_citations) inside the shared DB.
        """
        table_name = _validate_ident(table_name, kind="table_name")
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
            col_defs.append('"created_at" TIMESTAMP WITH TIME ZONE DEFAULT now()')

            cols_sql = ", ".join(col_defs)
            create_table_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (id SERIAL PRIMARY KEY, {cols_sql})'
            cur.execute(create_table_sql)

            # Insert rows
            inserted = 0
            if rows:
                safe_cols = [snake_case(c) for c in columns]
                insert_cols = [f'"{c}"' for c in safe_cols] + ['"cit_id"', '"fulltext_url"', '"fulltext"', '"fulltext_md5"']
                placeholders = ", ".join(["%s"] * len(insert_cols))
                insert_sql = f'INSERT INTO "{table_name}" ({", ".join(insert_cols)}) VALUES ({placeholders})'

                def _row_has_data(row: dict) -> bool:
                    for orig_col in columns:
                        v = row.get(orig_col)
                        if isinstance(v, str) and v.strip() != "":
                            return True
                    return False

                filtered_rows = [r for r in rows if _row_has_data(r)]

                values = []
                for r in filtered_rows:
                    row_vals = [r.get(orig_col) if r.get(orig_col) is not None else None for orig_col in columns]
                    row_vals.append(r.get("cit_id") if r.get("cit_id") is not None else None)
                    row_vals.append(r.get("fulltext_url") if r.get("fulltext_url") is not None else None)
                    row_vals.append(r.get("fulltext") if r.get("fulltext") is not None else None)
                    row_vals.append(r.get("fulltext_md5") if r.get("fulltext_md5") is not None else None)
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

    def load_include_columns_from_criteria(self, sr_doc: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Load the 'include' list for L1 screening.
        Mirrors logic previously embedded in the citations router but kept here
        so other modules (screen/extract) can reuse it without importing the router.
        """
        # 1) try SR-specific parsed criteria
        try:
            if sr_doc and isinstance(sr_doc, dict):
                cp = sr_doc.get("criteria_parsed") or sr_doc.get("criteria")
                if cp and isinstance(cp, dict):
                    if "l1" in cp and isinstance(cp.get("l1"), dict):
                        inc = cp.get("l1", {}).get("include")
                        if isinstance(inc, list) and inc:
                            return inc
                    inc2 = cp.get("include") if isinstance(cp, dict) else None
                    if isinstance(inc2, list) and inc2:
                        return inc2
        except Exception:
            pass

        # 2) fallback to project file
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "sr_setup", "configs", "criteria_config_measles_updated.yaml")
        cfg_path = os.path.normpath(cfg_path)
        try:
            import yaml

            with open(cfg_path, "r") as f:
                cfg = yaml.safe_load(f)
                include = cfg.get("include", [])
                if not isinstance(include, list):
                    return []
                return include
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def build_combined_citation_from_row(self, row: Dict[str, Any], include_columns: List[str]) -> str:
        parts: List[str] = []
        if not row:
            return ""
        for col in include_columns:
            snake = snake_case(col)
            val = row.get(snake)
            if val is None:
                continue
            parts.append(f"{col}: {val}  \n")
        return "".join(parts)


# module-level instance
cits_dp_service = CitsDPService()
