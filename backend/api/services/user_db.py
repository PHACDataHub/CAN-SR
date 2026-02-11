"""backend.api.services.user_db

User database service.

Historically this project stored users inside Azure Blob Storage directly.
To support multiple storage backends (local / azure / entra) we now build the
user DB on top of the common `storage_service` abstraction.

Storage keys used:
  system/user_registry.json

This file intentionally avoids importing Azure SDK packages so that local
deployments can run without them.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from passlib.context import CryptContext

from ..models.auth import UserCreate, UserRead
from .storage import storage_service


class UserDatabaseService:
    """Service for managing user data in the configured storage backend."""

    def __init__(self):
        if not storage_service:
            raise RuntimeError(
                "Storage is not configured. User database is unavailable."
            )
        self.storage = storage_service
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def _get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    def _registry_path(self) -> str:
        # Keep legacy layout: <container>/system/user_registry.json
        return f"{self.storage.container_name}/system/user_registry.json"

    async def _load_user_registry(self) -> Dict[str, Any]:
        """Load the user registry from storage."""
        try:
            content, _filename = await self.storage.get_bytes_by_path(self._registry_path())
            return json.loads(content.decode("utf-8"))
        except Exception:
            # Create empty registry if it doesn't exist / cannot be read
            return {"users": {}, "email_index": {}}

    async def _save_user_registry(self, registry: Dict[str, Any]) -> bool:
        """Save the user registry to storage."""
        try:
            payload = json.dumps(registry, indent=2).encode("utf-8")
            return await self.storage.put_bytes_by_path(
                self._registry_path(),
                payload,
                content_type="application/json",
            )
        except Exception:
            return False

    async def create_user(self, user_data: UserCreate) -> Optional[UserRead]:
        try:
            registry = await self._load_user_registry()

            if user_data.email in registry["email_index"]:
                return None

            user_id = str(uuid.uuid4())
            user_record = {
                "id": user_id,
                "email": user_data.email,
                "full_name": user_data.full_name,
                "hashed_password": self._get_password_hash(user_data.password),
                "is_active": True,
                "is_superuser": False,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "last_login": None,
            }

            registry["users"][user_id] = user_record
            registry["email_index"][user_data.email] = user_id

            if not await self._save_user_registry(registry):
                return None

            await self.storage.create_user_directory(user_id)

            return UserRead(
                id=user_id,
                email=user_record["email"],
                full_name=user_record["full_name"],
                is_active=user_record["is_active"],
                is_superuser=user_record["is_superuser"],
                created_at=user_record["created_at"],
            )
        except Exception:
            return None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        try:
            registry = await self._load_user_registry()
            if email not in registry["email_index"]:
                return None
            user_id = registry["email_index"][email]
            return registry["users"].get(user_id)
        except Exception:
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            registry = await self._load_user_registry()
            return registry["users"].get(user_id)
        except Exception:
            return None

    async def authenticate_user(self, email: str, password: str, sso: bool) -> Optional[Dict[str, Any]]:
        try:
            user = await self.get_user_by_email(email)
            if not user:
                return None
            if not sso and not self._verify_password(password, user["hashed_password"]):
                return None

            user["last_login"] = datetime.utcnow().isoformat()
            await self.update_user(user["id"], {"last_login": user["last_login"]})
            return user
        except Exception:
            return None

    async def update_user(self, user_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            registry = await self._load_user_registry()
            if user_id not in registry["users"]:
                return None

            user_record = registry["users"][user_id]
            user_record.update(update_data)
            user_record["updated_at"] = datetime.utcnow().isoformat()

            if await self._save_user_registry(registry):
                return user_record
            return None
        except Exception:
            return None

    async def deactivate_user(self, user_id: str) -> bool:
        result = await self.update_user(user_id, {"is_active": False})
        return result is not None

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        registry = await self._load_user_registry()
        users = list(registry.get("users", {}).values())
        users.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return users[skip : skip + limit]

    async def get_all_users(self) -> List[Dict[str, Any]]:
        registry = await self._load_user_registry()
        users = list(registry.get("users", {}).values())
        users.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return users

    async def get_user_count(self) -> int:
        registry = await self._load_user_registry()
        return len(registry.get("users", {}))


# Global instance
try:
    user_db_service: Optional[UserDatabaseService] = UserDatabaseService()
except Exception:
    user_db_service = None

user_db = user_db_service
