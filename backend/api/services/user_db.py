from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

from passlib.context import CryptContext

from ..models.auth import UserCreate, UserRead
from .postgres_auth import postgres_server

logger = logging.getLogger(__name__)


class UserDatabaseService:
    """Service for managing user data in PostgreSQL via psycopg3 async."""

    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        # Very small in-memory cache to avoid reading user_registry.json from storage
        # on every authenticated request (e.g., polling endpoints).
        self._registry_cache: Optional[Dict[str, Any]] = None
        self._registry_cache_ts: float = 0.0
        self._registry_cache_ttl_s: float = 30.0
        self._registry_cache_lock = asyncio.Lock()

    @staticmethod
    def _serialize_dates(row: Dict[str, Any]) -> Dict[str, Any]:
        for field in ("created_at", "updated_at", "last_login"):
            if row.get(field) and isinstance(row[field], datetime):
                row[field] = row[field].isoformat()
        return row

    def _get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    # ------------------------------------------------------------------
    # Table initialisation (called from FastAPI startup event)
    # ------------------------------------------------------------------

    async def _load_user_registry(self) -> Dict[str, Any]:
        """Load the user registry from storage."""
        async with self._registry_cache_lock:
            now = asyncio.get_running_loop().time()
            if (
                self._registry_cache is not None
                and (now - self._registry_cache_ts) < self._registry_cache_ttl_s
            ):
                return self._registry_cache

            try:
                content, _filename = await self.storage.get_bytes_by_path(
                    self._registry_path()
                )
                reg = json.loads(content.decode("utf-8"))
            except Exception:
                # Create empty registry if it doesn't exist / cannot be read
                reg = {"users": {}, "email_index": {}}

            self._registry_cache = reg
            self._registry_cache_ts = now
            return reg

    async def _save_user_registry(self, registry: Dict[str, Any]) -> bool:
        """Save the user registry to storage."""
        try:
            payload = json.dumps(registry, indent=2).encode("utf-8")
            ok = await self.storage.put_bytes_by_path(
                self._registry_path(),
                payload,
                content_type="application/json",
            )
            # Best-effort: update cache to reflect new registry
            if ok:
                async with self._registry_cache_lock:
                    self._registry_cache = registry
                    self._registry_cache_ts = asyncio.get_running_loop().time()
            return ok
        except Exception:
            return False

    async def ensure_table_exists(self) -> None:
        """Create the users table if it does not already exist."""
        try:
            async with postgres_server.aconn() as conn:
                await conn.execute("""
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
                    """)
            logger.info("Ensured users table exists")
        except Exception as e:
            logger.exception("Failed to ensure users table exists: %s", e)
            raise

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def create_user(self, user_data: UserCreate) -> Optional[UserRead]:
        try:
            async with postgres_server.aconn() as conn:
                email = user_data.email.lower()
                cur = await conn.execute(
                    "SELECT id FROM users WHERE email = %s", (email,)
                )
                if await cur.fetchone():
                    return None  # duplicate email

                user_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc)
                hashed_password = self._get_password_hash(user_data.password)
                await conn.execute(
                    """
                    INSERT INTO users
                        (id, email, full_name, hashed_password, is_active, is_superuser,
                         created_at, updated_at, last_login)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        email,
                        user_data.full_name,
                        hashed_password,
                        True,
                        False,
                        now,
                        now,
                        None,
                    ),
                )
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
            logger.exception("create_user failed")
            return None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        try:
            async with postgres_server.aconn() as conn:
                cur = await conn.execute(
                    "SELECT * FROM users WHERE email = %s", (email.lower(),)
                )
                row = await cur.fetchone()
                return self._serialize_dates(row) if row else None
        except Exception:
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with postgres_server.aconn() as conn:
                cur = await conn.execute(
                    "SELECT * FROM users WHERE id = %s", (user_id,)
                )
                row = await cur.fetchone()
                return self._serialize_dates(row) if row else None
        except Exception:
            return None

    async def authenticate_user(
        self, email: str, password: str, sso: bool = False
    ) -> Optional[Dict[str, Any]]:
        try:
            async with postgres_server.aconn() as conn:
                cur = await conn.execute(
                    "SELECT * FROM users WHERE email = %s", (email.lower(),)
                )
                row = await cur.fetchone()
                if not row:
                    return None
                if not sso and not self._verify_password(
                    password, row["hashed_password"]
                ):
                    return None
                now = datetime.now(timezone.utc)
                await conn.execute(
                    "UPDATE users SET last_login = %s WHERE id = %s", (now, row["id"])
                )
                row["last_login"] = now.isoformat()
                return self._serialize_dates(row)
        except Exception:
            return None

    async def update_user(
        self, user_id: str, update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed_fields = {
            "full_name",
            "email",
            "hashed_password",
            "is_active",
            "is_superuser",
            "last_login",
        }
        fields = {k: v for k, v in update_data.items() if k in allowed_fields}
        if not fields:
            return await self.get_user_by_id(user_id)

        try:
            async with postgres_server.aconn() as conn:
                now = datetime.now(timezone.utc)
                set_clause = ", ".join(f"{k} = %s" for k in fields)
                values = list(fields.values()) + [now, user_id]
                cur = await conn.execute(
                    f"UPDATE users SET {set_clause}, updated_at = %s WHERE id = %s",
                    values,
                )
                if cur.rowcount == 0:
                    return None
            return await self.get_user_by_id(user_id)
        except Exception:
            return None

    async def deactivate_user(self, user_id: str) -> bool:
        result = await self.update_user(user_id, {"is_active": False})
        return result is not None

    async def get_all_users(self) -> List[Dict[str, Any]]:
        try:
            async with postgres_server.aconn() as conn:
                cur = await conn.execute("SELECT * FROM users ORDER BY created_at DESC")
                rows = await cur.fetchall()
                return [self._serialize_dates(row) for row in rows]
        except Exception:
            return []

    async def get_user_count(self) -> int:
        try:
            async with postgres_server.aconn() as conn:
                cur = await conn.execute("SELECT COUNT(*) FROM users")
                row = await cur.fetchone()
                return row["count"] if row else 0
        except Exception:
            return 0


# Global instance — matches the name expected by security.py and sr/router.py
try:
    user_db_service: Optional[UserDatabaseService] = UserDatabaseService()
except Exception:
    user_db_service = None

user_db = user_db_service
