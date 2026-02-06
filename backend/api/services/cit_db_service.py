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
from typing import Any, Dict, List, Optional
import psycopg2
import psycopg2.extras
import json
import re
import os
import io
import urllib.parse as up
import hashlib

# Local settings import (for POSTGRES_ADMIN_DSN / DATABASE_URL usage)
try:
    from ..core.config import settings
except Exception:
    settings = None

from .postgres_auth import postgres_server


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
    def create_column(self, db_conn_str: str, col: str, col_type: str, table_name: str = "citations") -> None:
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
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def update_jsonb_column(
        self,
        db_conn_str: str,
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
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return rows or 0
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def update_text_column(
        self,
        db_conn_str: str,
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
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return rows or 0
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    # -----------------------
    # Citation row helpers
    # -----------------------
    def dump_citations_csv(self, db_conn_str: str, table_name: str = "citations") -> bytes:
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

            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass

            return csv_text.encode("utf-8")
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def get_citation_by_id(self, db_conn_str: str, citation_id: int, table_name: str = "citations") -> Optional[Dict[str, Any]]:
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
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    postgres_server.close()
                except Exception:
                    pass
                return None
            if isinstance(row, dict):
                result = row
            else:
                cols = [desc[0] for desc in cur.description]
                result = {cols[i]: row[i] for i in range(len(cols))}
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return result
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def list_citation_ids(self, db_conn_str: str, filter_step=None, table_name: str = "citations") -> List[int]:
        """
        Return list of integer primary keys (id) from citations table ordered by id.
        """
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            if filter_step is not None:

                human_col = f"human_{filter_step}_decision"
                llm_col = f"llm_{filter_step}_decision"

                try:
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{llm_col}" TEXT')
                except Exception:
                    try:
                        cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{llm_col}" TEXT')
                    except Exception:
                        pass
                        
                try: 
                    cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{human_col}" TEXT')
                except Exception:
                    try:
                        cur.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{human_col}" TEXT')
                    except Exception:
                        pass

                query = f'''
                SELECT id FROM "{table_name}"
                WHERE {human_col} != 'exclude' OR {human_col} IS NULL
                AND ({human_col} = 'include' OR {llm_col} = 'include')
                ORDER BY id
                '''

            else: query = f'SELECT id FROM "{table_name}" ORDER BY id'

            cur.execute(query)
            rows = cur.fetchall()
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return [int(r[0]) for r in rows]
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def list_fulltext_urls(self, db_conn_str: str, table_name: str = "citations") -> List[str]:
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
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return [r[0] for r in rows if r and r[0]]
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def update_citation_fulltext(self, db_conn_str: str, citation_id: int, fulltext_path: str) -> int:
        """
        Backwards-compatible helper used by some routers. Sets `fulltext_url`.
        """
        return self.update_text_column(db_conn_str, citation_id, "fulltext_url", fulltext_path)

    # -----------------------
    # Upload fulltext and compute md5
    # -----------------------
    def attach_fulltext(
        self,
        db_conn_str: str,
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
        self.create_column(db_conn_str, "fulltext_url", "TEXT", table_name=table_name)
        # compute md5
        md5 = hashlib.md5(file_bytes).hexdigest() if file_bytes is not None else ""
        
        # update both columns in one statement
        conn = postgres_server.conn
        cur = conn.cursor()
        cur.execute(f'UPDATE "{table_name}" SET "fulltext_url" = %s WHERE id = %s', (azure_path, int(citation_id)))
        rows = cur.rowcount
        conn.commit()

        cur.close()
        postgres_server.close()
        return rows

    # -----------------------
    # Column get/set helpers
    # -----------------------
    def get_column_value(self, db_conn_str: str, citation_id: int, column: str, table_name: str = "citations") -> Any:
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
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    postgres_server.close()
                except Exception:
                    pass
                return None
            # row may be dict or tuple
            if isinstance(row, dict):
                val = list(row.values())[0] if row else None
            else:
                val = row[0] if row and len(row) > 0 else None
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return val
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def set_column_value(self, db_conn_str: str, citation_id: int, column: str, value: Any, table_name: str = "citations") -> int:
        """
        Generic setter for a citation row column. Will create a TEXT column if it doesn't exist.
        """
        # For simplicity, create a TEXT column. Callers that need JSONB should use update_jsonb_column.
        self.create_column(db_conn_str, column, "TEXT", table_name=table_name)
        return self.update_text_column(db_conn_str, citation_id, column, value if value is not None else None, table_name=table_name)

    # -----------------------
    # Per-upload table lifecycle helpers
    # -----------------------
    def drop_table(self, db_conn_str: str, table_name: str, cascade: bool = True) -> None:
        """Drop a screening table in the shared database."""
        table_name = _validate_ident(table_name, kind="table_name")
        conn = None
        try:
            conn = postgres_server.conn
            conn.autocommit = True
            cur = conn.cursor()
            cas = " CASCADE" if cascade else ""
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}"{cas}')
            try:
                cur.close()
            except Exception:
                pass
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
                    pass

    def create_table_and_insert_sync(
        self,
        db_conn_str: str,
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
            try:
                cur.close()
            except Exception:
                pass
            try:
                postgres_server.close()
            except Exception:
                pass
            return inserted
        finally:
            if conn:
                try:
                    postgres_server.close()
                except Exception:
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
