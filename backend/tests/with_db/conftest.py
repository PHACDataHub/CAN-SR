from contextlib import asynccontextmanager
import os

import psycopg2
import psycopg2.sql
import pytest

from api.core.config import settings
from api.services.postgres_auth import postgres_server
from api.services.user_db import  user_db_service
from api.services.sr_db_service import srdb_service


def _derive_test_db_name(base_name: str) -> str:
    if base_name.endswith("_test"):
        return f"{base_name}_session"
    return f"{base_name}_test"


def _connection_kwargs(database: str) -> dict:
    profile = settings.postgres_profile()
    kwargs = {
        "host": profile.get("host"),
        "dbname": database,
        "user": profile.get("user"),
        "password": profile.get("password"),
        "port": int(profile.get("port") or 5432),
        "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "3")),
    }
    sslmode = profile.get("sslmode")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs


def _admin_connection(database: str):
    conn = psycopg2.connect(
        **_connection_kwargs(database),
    )
    conn.autocommit = True
    return conn


def _drop_database_if_exists(admin_database: str, database_name: str) -> None:
    conn = _admin_connection(admin_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            cur.execute(
                psycopg2.sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    psycopg2.sql.Identifier(database_name)
                )
            )
    finally:
        conn.close()


def _create_database(admin_database: str, database_name: str) -> None:
    conn = _admin_connection(admin_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                psycopg2.sql.SQL("CREATE DATABASE {}").format(
                    psycopg2.sql.Identifier(database_name)
                )
            )
    finally:
        conn.close()

"""
Note on proxies and monkeypatching:

 - UserDatabaseService and other code call postgres_server.aconn(), which normally opens a brand new connection each time
  - A per-test rollback only works if all DB work for that test goes through the same connection object
  - The proxy makes commit() effectively a no-op and keeps all async calls on the same connection until the fixture rolls it back at teardown
  - The sync proxy covers code paths that use postgres_server.conn directly

  Without the proxy:

  - each aconn() block would open/close its own connection and commit on exit
  - the final fixture rollback would not undo those committed changes
  - the tests would stop being isolated

TODO: clean this up with a better approach:
- refactor services to use some kind of managed connection that can be overridden in tests without monkeypatching 
- I think this is what django does?

"""

class _SyncConnectionProxy:
    def __init__(self, conn):
        self._conn = conn

    @property
    def closed(self):
        return self._conn.closed

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return None

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def get_transaction_status(self):
        return self._conn.get_transaction_status()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _AsyncCursorProxy:
    def __init__(self, cursor):
        self._cursor = cursor

    class _RowAdapter:
        """
        hacky: some code (sr, sync) expects dict-like access to rows, other (user, async) expects tuple-like access

        This accommodates both, but only in tests! In production or dev, only one will work at a time

        why did we do this? See comment on proxies above, 
        it was difficult to patch single behavior without both,
        and this was a lighter touch on existing code

        """
        def __init__(self, row, description):
            self._row = list(row)
            self._columns = [desc[0] for desc in description or []]
            self._index = {name: idx for idx, name in enumerate(self._columns)}

        def __getitem__(self, key):
            if isinstance(key, str):
                return self._row[self._index[key]]
            return self._row[key]

        def __setitem__(self, key, value):
            if isinstance(key, str):
                self._row[self._index[key]] = value
            else:
                self._row[key] = value

        def get(self, key, default=None):
            try:
                return self[key]
            except (KeyError, IndexError, TypeError):
                return default

        def keys(self):
            return list(self._columns)

        def items(self):
            return [(name, self[name]) for name in self._columns]

        def values(self):
            return [self[name] for name in self._columns]

        def __contains__(self, key):
            return key in self._index

        def __len__(self):
            return len(self._row)

    async def fetchone(self):
        row = self._cursor.fetchone()
        return self._RowAdapter(row, self._cursor.description) if row is not None else None

    async def fetchall(self):
        return [self._RowAdapter(row, self._cursor.description) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _AsyncConnectionProxy:
    def __init__(self, conn):
        self._conn = conn

    async def execute(self, query, params=None):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return _AsyncCursorProxy(cursor)

    async def commit(self):
        return None

    async def rollback(self):
        return self._conn.rollback()

    async def close(self):
        return self._conn.close()

    def get_transaction_status(self):
        return self._conn.get_transaction_status()

    @property
    def closed(self):
        return self._conn.closed


@pytest.fixture(scope="session", autouse=True)
def test_postgres_database():
    original_database = settings.POSTGRES_DATABASE
    if not original_database:
        raise RuntimeError("POSTGRES_DATABASE must be set for with_db tests")

    test_database = _derive_test_db_name(original_database)

    _drop_database_if_exists(original_database, test_database)
    _create_database(original_database, test_database)

    settings.POSTGRES_DATABASE = test_database
    postgres_server.close()

    try:
        yield test_database
    finally:
        postgres_server.close()
        settings.POSTGRES_DATABASE = original_database
        _drop_database_if_exists(original_database, test_database)


@pytest.fixture(scope="session", autouse=True)
async def seed_database(test_postgres_database):
    """
    Rather than touch 'test_postgres_database', add business logic here to create tables and seed any necessary data
    """
    srdb_service.ensure_table_exists()

    await user_db_service.ensure_table_exists()




@pytest.fixture(autouse=True)
async def db_transaction(test_postgres_database, monkeypatch):
    sync_conn = psycopg2.connect(
        **_connection_kwargs(test_postgres_database),
    )
    sync_proxy = _SyncConnectionProxy(sync_conn)
    async_proxy = _AsyncConnectionProxy(sync_proxy)

    @asynccontextmanager
    async def _patched_aconn():
        yield async_proxy

    monkeypatch.setattr(postgres_server, "_conn", sync_proxy, raising=False)
    monkeypatch.setattr(postgres_server, "aconn", _patched_aconn, raising=False)

    try:
        yield
    finally:
        try:
            sync_conn.rollback()
        finally:
            sync_conn.close()
