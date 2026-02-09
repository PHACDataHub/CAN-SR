"""User database service using Azure Blob Storage"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from passlib.context import CryptContext

from ..core.config import settings
from ..models.auth import UserCreate, UserRead


class UserDatabaseService:
    """Service for managing user data in Azure Blob Storage"""

    def __init__(self):
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            raise ValueError("Azure Storage connection string not configured")

        self.blob_service_client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        self.container_name = settings.AZURE_STORAGE_CONTAINER_NAME
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        self._ensure_container_exists()

    def _ensure_container_exists(self):
        """Ensure the storage container exists"""
        try:
            self.blob_service_client.create_container(self.container_name)
        except Exception:
            pass

    def _get_password_hash(self, password: str) -> str:
        """Get password hash"""
        return self.pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash"""
        return self.pwd_context.verify(plain_password, hashed_password)

    async def _load_user_registry(self) -> Dict[str, Any]:
        """Load the user registry from blob storage"""
        try:
            blob_name = "system/user_registry.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            blob_data = blob_client.download_blob().readall()
            return json.loads(blob_data.decode("utf-8"))
        except ResourceNotFoundError:
            # Create empty registry if it doesn't exist
            return {"users": {}, "email_index": {}}
        except Exception as e:
            print(f"Error loading user registry: {e}")
            return {"users": {}, "email_index": {}}

    async def _save_user_registry(self, registry: Dict[str, Any]) -> bool:
        """Save the user registry to blob storage"""
        try:
            blob_name = "system/user_registry.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            registry_json = json.dumps(registry, indent=2)
            blob_client.upload_blob(registry_json, overwrite=True)
            return True
        except Exception as e:
            print(f"Error saving user registry: {e}")
            return False

    async def create_user(self, user_data: UserCreate) -> Optional[UserRead]:
        """Create a new user"""
        try:
            registry = await self._load_user_registry()

            # Check if user already exists
            if user_data.email in registry["email_index"]:
                return None  # User already exists

            # Generate unique user ID
            user_id = str(uuid.uuid4())

            # Create user record
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

            # Add to registry
            registry["users"][user_id] = user_record
            registry["email_index"][user_data.email] = user_id

            # Save registry
            if await self._save_user_registry(registry):
                # Create user directory structure in storage
                from .storage import storage_service

                if storage_service:
                    await storage_service.create_user_directory(user_id)

                # User collections will be created on first login via auth router

                # Note: Base knowledge is initialized once at startup, not per user

                return UserRead(
                    id=user_id,
                    email=user_record["email"],
                    full_name=user_record["full_name"],
                    is_active=user_record["is_active"],
                    is_superuser=user_record["is_superuser"],
                    created_at=user_record["created_at"],
                )

            return None
        except Exception as e:
            print(f"Error creating user: {e}")
            return None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get a user by email"""
        try:
            registry = await self._load_user_registry()

            if email not in registry["email_index"]:
                return None

            user_id = registry["email_index"][email]
            return registry["users"].get(user_id)
        except Exception as e:
            print(f"Error getting user by email: {e}")
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a user by ID"""
        try:
            registry = await self._load_user_registry()
            return registry["users"].get(user_id)
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None

    async def authenticate_user(
        self, email: str, password: str, sso: bool
    ) -> Optional[Dict[str, Any]]:
        """Authenticate a user"""
        try:
            user = await self.get_user_by_email(email)
            if not user:
                return None

            if not sso and not self._verify_password(password, user["hashed_password"]):
                return None

            # Update last login
            user["last_login"] = datetime.utcnow().isoformat()
            await self.update_user(user["id"], {"last_login": user["last_login"]})

            return user
        except Exception as e:
            print(f"Error authenticating user: {e}")
            return None

    async def update_user(
        self, user_id: str, update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update user data"""
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
        except Exception as e:
            print(f"Error updating user: {e}")
            return None

    async def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user"""
        try:
            result = await self.update_user(user_id, {"is_active": False})
            return result is not None
        except Exception as e:
            print(f"Error deactivating user: {e}")
            return False

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """List all users (for admin purposes)"""
        try:
            registry = await self._load_user_registry()
            users = list(registry["users"].values())

            users.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            return users[skip : skip + limit]
        except Exception as e:
            print(f"Error listing users: {e}")
            return []

    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users (for admin purposes)"""
        try:
            registry = await self._load_user_registry()
            users = list(registry["users"].values())

            users.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            return users
        except Exception as e:
            print(f"Error getting all users: {e}")
            return []

    async def get_user_count(self) -> int:
        """Get total number of users"""
        try:
            registry = await self._load_user_registry()
            return len(registry["users"])
        except Exception as e:
            print(f"Error getting user count: {e}")
            return 0


# Global user database service instance
user_db_service = (
    UserDatabaseService() if settings.AZURE_STORAGE_CONNECTION_STRING else None
)

# Alias for backward compatibility
user_db = user_db_service
