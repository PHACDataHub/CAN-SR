"""backend.api.services.user_db

User database service — PostgreSQL implementation.

Replaces the previous Azure Storage JSON-based user registry.
Uses the same public async interface so that callers (security.py,
auth/router.py, sr/router.py) require no changes.

Storage: PostgreSQL `users` table (created on startup via ensure_table_exists).

Table schema:
    id            TEXT PRIMARY KEY
    email         TEXT UNIQUE NOT NULL
    full_name     TEXT NOT NULL
    hashed_password TEXT NOT NULL
    is_active     BOOLEAN DEFAULT TRUE
    is_superuser  BOOLEAN DEFAULT FALSE
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT now()
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT now()
    last_login    TIMESTAMP WITH TIME ZONE

All blocking psycopg2 calls are synchronous (matching the pattern in
sr_db_service.py) and are wrapped with asyncio.get_running_loop().run_in_executor
so async callers can await them directly without a run_in_threadpool call-site.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

from passlib.context import CryptContext

from ..models.auth import UserCreate, UserRead
from .postgres_auth import postgres_server

logger = logging.getLogger(__name__)


def _parse_row(row: tuple, cursor) -> Dict[str, Any]:
    """Convert a psycopg2 row tuple into a dict, serialising datetimes to ISO strings."""
    cols = [desc[0] for desc in cursor.description]
    doc: Dict[str, Any] = {cols[i]: row[i] for i in range(len(cols))}
    for field in ("created_at", "updated_at", "last_login"):
        if doc.get(field) and isinstance(doc[field], datetime):
            doc[field] = doc[field].isoformat()
    return doc


class UserDatabaseService:
    """Service for managing user data in PostgreSQL."""

    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def _get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    # ------------------------------------------------------------------
    # Table initialisation (called from FastAPI startup event)
    # ------------------------------------------------------------------

    def ensure_table_exists(self) -> None:
        """Create the users table if it does not already exist."""
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id              TEXT PRIMARY KEY,
                    email           TEXT UNIQUE NOT NULL,
                    full_name       TEXT NOT NULL,
                    hashed_password TEXT NOT NULL,
                    is_active       BOOLEAN DEFAULT TRUE,
                    is_superuser    BOOLEAN DEFAULT FALSE,
                    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    last_login      TIMESTAMP WITH TIME ZONE
                )
                """
            )
            conn.commit()
            logger.info("Ensured users table exists")
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception("Failed to ensure users table exists: %s", e)
            raise

    # ------------------------------------------------------------------
    # Synchronous DB helpers (run inside a thread-pool executor)
    # ------------------------------------------------------------------

    def _create_user_sync(self, user_data: UserCreate) -> Optional[UserRead]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()

            email = user_data.email.lower()
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return None  # Duplicate email

            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            hashed_password = self._get_password_hash(user_data.password)

            cur.execute(
                """
                INSERT INTO users
                    (id, email, full_name, hashed_password, is_active, is_superuser,
                     created_at, updated_at, last_login)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, email, user_data.full_name, hashed_password,
                 True, False, now, now, None),
            )
            conn.commit()

            return UserRead(
                id=user_id,
                email=email,
                full_name=user_data.full_name,
                is_active=True,
                is_superuser=False,
                created_at=now,
                last_login=None,
            )
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return None

    def _get_user_by_email_sync(self, email: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE email = %s", (email.lower(),))
            row = cur.fetchone()
            if not row:
                return None
            return _parse_row(row, cur)
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return None

    def _get_user_by_id_sync(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return _parse_row(row, cur)
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return None

    def _authenticate_user_sync(
        self, email: str, password: str, sso: bool
    ) -> Optional[Dict[str, Any]]:
        user = self._get_user_by_email_sync(email)
        if not user:
            return None
        if not sso and not self._verify_password(password, user["hashed_password"]):
            return None

        # Record last login
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            cur.execute(
                "UPDATE users SET last_login = %s WHERE id = %s",
                (now, user["id"]),
            )
            conn.commit()
            user["last_login"] = now.isoformat()
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass

        return user

    def _update_user_sync(
        self, user_id: str, update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed_fields = {
            "full_name", "email", "hashed_password",
            "is_active", "is_superuser", "last_login",
        }
        fields = {k: v for k, v in update_data.items() if k in allowed_fields}
        if not fields:
            return self._get_user_by_id_sync(user_id)

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            set_clause = ", ".join(f"{k} = %s" for k in fields)
            values = list(fields.values()) + [now, user_id]
            cur.execute(
                f"UPDATE users SET {set_clause}, updated_at = %s WHERE id = %s",
                values,
            )
            if cur.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
            return self._get_user_by_id_sync(user_id)
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return None

    def _deactivate_user_sync(self, user_id: str) -> bool:
        result = self._update_user_sync(user_id, {"is_active": False})
        return result is not None

    def _list_users_sync(self, skip: int, limit: int) -> List[Dict[str, Any]]:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, skip),
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            results = []
            for row in rows:
                doc = {cols[i]: row[i] for i in range(len(cols))}
                for field in ("created_at", "updated_at", "last_login"):
                    if doc.get(field) and isinstance(doc[field], datetime):
                        doc[field] = doc[field].isoformat()
                results.append(doc)
            return results
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return []

    def _get_user_count_sync(self) -> int:
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            row = cur.fetchone()
            return row[0] if row else 0
        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return 0

    # ------------------------------------------------------------------
    # Public async interface (same signatures as the previous implementation)
    # ------------------------------------------------------------------

    async def create_user(self, user_data: UserCreate) -> Optional[UserRead]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._create_user_sync, user_data)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_user_by_email_sync, email)

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_user_by_id_sync, user_id)

    async def authenticate_user(
        self, email: str, password: str, sso: bool = False
    ) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._authenticate_user_sync, email, password, sso
        )

    async def update_user(
        self, user_id: str, update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._update_user_sync, user_id, update_data
        )

    async def deactivate_user(self, user_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._deactivate_user_sync, user_id)

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_users_sync, skip, limit)

    async def get_all_users(self) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_users_sync, 0, 10_000)

    async def get_user_count(self) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_user_count_sync)


# Global instance — matches the name expected by security.py and sr/router.py
try:
    user_db_service: Optional[UserDatabaseService] = UserDatabaseService()
except Exception:
    user_db_service = None

user_db = user_db_service
