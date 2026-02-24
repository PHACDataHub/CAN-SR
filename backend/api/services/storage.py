"""backend.api.services.storage

Storage abstraction for CAN-SR.

Supported backends (selected via STORAGE_MODE):
* local - Local filesystem storage (backed by docker compose volume)
* azure - Azure Blob Storage via **account name + key** (strict)
* entra - Azure Blob Storage via **DefaultAzureCredential** (Entra/Managed Identity) (strict)

Routers should not access Azure SDK objects directly.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

try:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
except Exception:  # pragma: no cover
    # Allow local-storage deployments/environments to import without azure packages.
    ResourceNotFoundError = Exception  # type: ignore
    DefaultAzureCredential = None  # type: ignore
    BlobSasPermissions = None  # type: ignore
    BlobServiceClient = None  # type: ignore
    generate_blob_sas = None  # type: ignore

from ..core.config import settings
from ..utils.file_hash import create_file_metadata

logger = logging.getLogger(__name__)


class StorageService(Protocol):
    """Common API that both Azure and local storage must implement."""

    container_name: str

    async def create_user_directory(self, user_id: str) -> bool: ...
    async def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool: ...
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]: ...
    async def upload_user_document(self, user_id: str, filename: str, file_content: bytes) -> Optional[str]: ...
    async def get_user_document(self, user_id: str, doc_id: str, filename: str) -> Optional[bytes]: ...
    async def list_user_documents(self, user_id: str) -> List[Dict[str, Any]]: ...
    async def delete_user_document(self, user_id: str, doc_id: str, filename: str) -> bool: ...
    async def put_bytes_by_path(self, path: str, content: bytes, content_type: str = "application/octet-stream") -> bool: ...
    async def get_bytes_by_path(self, path: str) -> Tuple[bytes, str]: ...
    async def delete_by_path(self, path: str) -> bool: ...
    async def generate_signed_url(self, path: str, expiry_minutes: int = 5) -> Optional[str]: ...


# =============================================================================
# Azure Blob Storage
# =============================================================================


class AzureStorageService:
    """Service for managing user data in Azure Blob Storage."""

    def __init__(self, *, account_url: str | None = None, connection_string: str | None = None, container_name: str):
        if not BlobServiceClient:
            raise RuntimeError(
                "Azure storage libraries are not installed. Install azure-identity and azure-storage-blob, or use STORAGE_MODE=local."
            )

        if bool(account_url) == bool(connection_string):
            raise ValueError("Exactly one of account_url or connection_string must be provided")

        self._account_key: str | None = None
        self._credential: Any = None

        if connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            self._account_key = self._get_account_key_from_connection_str(connection_string)
        else:
            if not DefaultAzureCredential:
                raise RuntimeError(
                    "azure-identity is not installed. Install azure-identity, or use STORAGE_MODE=azure (connection string) or local."
                )
            self._credential = DefaultAzureCredential()
            self.blob_service_client = BlobServiceClient(account_url=account_url, credential=self._credential)

        self.container_name = container_name
        self._ensure_container_exists()
    
    def _get_account_key_from_connection_str(self, connection_str):
        for part in connection_str.split(";"):
            if part.startswith("AccountKey="):
                return part[len("AccountKey="):]
        return None

    def _ensure_container_exists(self):
        try:
            self.blob_service_client.create_container(self.container_name)
        except Exception:
            pass

    async def create_user_directory(self, user_id: str) -> bool:
        try:
            profile_data = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "document_count": 0,
                "storage_used": 0,
            }

            await self.save_user_profile(user_id, profile_data)

            # Create placeholder file to establish directory structure
            blob_name = f"users/{user_id}/documents/.placeholder"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.upload_blob(b"", overwrite=True)
            return True
        except Exception as e:
            logger.error("Error creating user directory for %s: %s", user_id, e)
            return False

    async def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool:
        try:
            blob_name = f"users/{user_id}/profile.json"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.upload_blob(json.dumps(profile_data, indent=2), overwrite=True)
            return True
        except Exception as e:
            logger.error("Error saving user profile for %s: %s", user_id, e)
            return False

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            blob_name = f"users/{user_id}/profile.json"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_data = blob_client.download_blob().readall()
            return json.loads(blob_data.decode("utf-8"))
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error("Error getting user profile for %s: %s", user_id, e)
            return None

    async def upload_user_document(self, user_id: str, filename: str, file_content: bytes) -> Optional[str]:
        try:
            doc_id = str(uuid.uuid4())
            blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.upload_blob(file_content, overwrite=True)

            file_metadata = create_file_metadata(
                filename,
                file_content,
                {
                    "document_id": doc_id,
                    "user_id": user_id,
                    "upload_date": datetime.now(timezone.utc).isoformat(),
                },
            )
            await self.save_file_hash_metadata(user_id, doc_id, file_metadata)

            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = int(profile.get("document_count", 0)) + 1
                profile["storage_used"] = int(profile.get("storage_used", 0)) + len(file_content)
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)

            return doc_id
        except Exception as e:
            logger.error("Error uploading document %s for user %s: %s", filename, user_id, e)
            return None

    async def get_user_document(self, user_id: str, doc_id: str, filename: str) -> Optional[bytes]:
        try:
            blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            return blob_client.download_blob().readall()
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error("Error getting document %s for user %s: %s", doc_id, user_id, e)
            return None

    async def list_user_documents(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            prefix = f"users/{user_id}/documents/"
            blobs = self.blob_service_client.get_container_client(self.container_name).list_blobs(name_starts_with=prefix)

            documents: List[Dict[str, Any]] = []
            for blob in blobs:
                if blob.name.endswith(".placeholder"):
                    continue
                blob_filename = blob.name.replace(prefix, "")
                if "_" not in blob_filename:
                    continue
                doc_id, filename = blob_filename.split("_", 1)

                hash_metadata = await self.get_file_hash_metadata(user_id, doc_id)
                document_info: Dict[str, Any] = {
                    "document_id": doc_id,
                    "filename": filename,
                    "file_size": blob.size,
                    "upload_date": blob.last_modified.isoformat(),
                    "last_modified": blob.last_modified.isoformat(),
                }
                if hash_metadata:
                    document_info["file_hash"] = hash_metadata.get("file_hash")
                    document_info["signature"] = hash_metadata.get("signature")
                documents.append(document_info)

            return documents
        except Exception as e:
            logger.error("Error listing user documents for %s: %s", user_id, e)
            return []

    async def delete_user_document(self, user_id: str, doc_id: str, filename: str) -> bool:
        try:
            doc_blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"
            doc_blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=doc_blob_name)

            try:
                doc_size = doc_blob_client.get_blob_properties().size
            except ResourceNotFoundError:
                doc_size = 0

            doc_blob_client.delete_blob()
            await self.delete_file_hash_metadata(user_id, doc_id)

            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = max(0, int(profile.get("document_count", 0)) - 1)
                profile["storage_used"] = max(0, int(profile.get("storage_used", 0)) - int(doc_size))
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)

            return True
        except Exception as e:
            logger.error("Error deleting document %s for user %s: %s", doc_id, user_id, e)
            return False

    async def save_file_hash_metadata(self, user_id: str, document_id: str, file_metadata: Dict[str, Any]) -> bool:
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.upload_blob(json.dumps(file_metadata, indent=2), overwrite=True)
            return True
        except Exception as e:
            logger.error("Error saving file metadata for %s: %s", document_id, e)
            return False

    async def get_file_hash_metadata(self, user_id: str, document_id: str) -> Optional[Dict[str, Any]]:
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            metadata_json = blob_client.download_blob().readall().decode("utf-8")
            return json.loads(metadata_json)
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error("Error getting file metadata for %s: %s", document_id, e)
            return None

    async def delete_file_hash_metadata(self, user_id: str, document_id: str) -> bool:
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            return True
        except Exception as e:
            logger.error("Error deleting file metadata for %s: %s", document_id, e)
            return False

    async def put_bytes_by_path(self, path: str, content: bytes, content_type: str = "application/octet-stream") -> bool:
        """Write blob by storage path 'container/blob'."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)
        blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob)
        blob_client.upload_blob(content, overwrite=True, content_type=content_type)
        return True

    async def get_bytes_by_path(self, path: str) -> Tuple[bytes, str]:
        """Read blob by storage path 'container/blob'. Returns (bytes, filename)."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)

        blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob)
        content = blob_client.download_blob().readall()
        filename = os.path.basename(blob) or "download"
        return content, filename

    async def delete_by_path(self, path: str) -> bool:
        """Delete blob by storage path 'container/blob'."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)
        blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob)
        blob_client.delete_blob()
        return True

    async def generate_signed_url(self, path: str, expiry_minutes: int = 5) -> Optional[str]:
        """Generate a read-only SAS URL for a blob. Path format: 'container/blob'."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)

        expiry = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
        account_name = self.blob_service_client.account_name

        blob_sas_kwargs = {
            "account_name": account_name,
            "container_name": container,
            "blob_name": blob,
            "permission": BlobSasPermissions(read=True),
            "expiry": expiry,
        }
        if self._account_key:
            sas_token = generate_blob_sas(**blob_sas_kwargs, account_key=self._account_key)
        elif self._credential:
            delegation_key = self.blob_service_client.get_user_delegation_key(
                key_start_time=datetime.now(timezone.utc) - timedelta(minutes=1),
                key_expiry_time=expiry,
            )
            sas_token = generate_blob_sas(**blob_sas_kwargs, user_delegation_key=delegation_key)
        else:
            raise RuntimeError("No credentials available for SAS generation")

        return f"https://{account_name}.blob.core.windows.net/{container}/{blob}?{sas_token}"


# =============================================================================
# Local filesystem storage
# =============================================================================


class LocalStorageService:
    """Local filesystem storage implementation.

    Layout:
      {LOCAL_STORAGE_BASE_PATH}/{STORAGE_CONTAINER_NAME}/users/{user_id}/...
    """

    def __init__(self):
        self.base_path = Path(settings.LOCAL_STORAGE_BASE_PATH).resolve()
        self.container_name = settings.STORAGE_CONTAINER_NAME
        (self.base_path / self.container_name).mkdir(parents=True, exist_ok=True)

    def _container_root(self) -> Path:
        return self.base_path / self.container_name

    def _user_root(self, user_id: str) -> Path:
        return self._container_root() / "users" / str(user_id)

    def _profile_path(self, user_id: str) -> Path:
        return self._user_root(user_id) / "profile.json"

    def _doc_path(self, user_id: str, doc_id: str, filename: str) -> Path:
        return self._user_root(user_id) / "documents" / f"{doc_id}_{filename}"

    def _metadata_path(self, user_id: str, doc_id: str) -> Path:
        return self._user_root(user_id) / "metadata" / f"{doc_id}_metadata.json"

    async def create_user_directory(self, user_id: str) -> bool:
        try:
            (self._user_root(user_id) / "documents").mkdir(parents=True, exist_ok=True)
            (self._user_root(user_id) / "metadata").mkdir(parents=True, exist_ok=True)

            if not self._profile_path(user_id).exists():
                profile_data = {
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "document_count": 0,
                    "storage_used": 0,
                }
                await self.save_user_profile(user_id, profile_data)
            return True
        except Exception as e:
            logger.error("Error creating user directory for %s: %s", user_id, e)
            return False

    async def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool:
        try:
            self._profile_path(user_id).parent.mkdir(parents=True, exist_ok=True)
            self._profile_path(user_id).write_text(json.dumps(profile_data, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("Error saving user profile for %s: %s", user_id, e)
            return False

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            p = self._profile_path(user_id)
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Error getting user profile for %s: %s", user_id, e)
            return None

    async def upload_user_document(self, user_id: str, filename: str, file_content: bytes) -> Optional[str]:
        try:
            await self.create_user_directory(user_id)
            doc_id = str(uuid.uuid4())
            doc_path = self._doc_path(user_id, doc_id, filename)
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_bytes(file_content)

            file_metadata = create_file_metadata(
                filename,
                file_content,
                {
                    "document_id": doc_id,
                    "user_id": user_id,
                    "upload_date": datetime.now(timezone.utc).isoformat(),
                },
            )
            await self.save_file_hash_metadata(user_id, doc_id, file_metadata)

            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = int(profile.get("document_count", 0)) + 1
                profile["storage_used"] = int(profile.get("storage_used", 0)) + len(file_content)
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)

            return doc_id
        except Exception as e:
            logger.error("Error uploading document %s for user %s: %s", filename, user_id, e)
            return None

    async def get_user_document(self, user_id: str, doc_id: str, filename: str) -> Optional[bytes]:
        try:
            p = self._doc_path(user_id, doc_id, filename)
            if not p.exists():
                return None
            return p.read_bytes()
        except Exception as e:
            logger.error("Error getting document %s for user %s: %s", doc_id, user_id, e)
            return None

    async def list_user_documents(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            docs_dir = self._user_root(user_id) / "documents"
            if not docs_dir.exists():
                return []

            documents: List[Dict[str, Any]] = []
            for p in docs_dir.iterdir():
                if not p.is_file():
                    continue
                name = p.name
                if "_" not in name:
                    continue
                doc_id, filename = name.split("_", 1)
                stat = p.stat()

                hash_metadata = await self.get_file_hash_metadata(user_id, doc_id)
                doc_info: Dict[str, Any] = {
                    "document_id": doc_id,
                    "filename": filename,
                    "file_size": stat.st_size,
                    "upload_date": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
                if hash_metadata:
                    doc_info["file_hash"] = hash_metadata.get("file_hash")
                    doc_info["signature"] = hash_metadata.get("signature")
                documents.append(doc_info)

            # stable ordering
            documents.sort(key=lambda d: d.get("upload_date", ""), reverse=True)
            return documents
        except Exception as e:
            logger.error("Error listing user documents for %s: %s", user_id, e)
            return []

    async def delete_user_document(self, user_id: str, doc_id: str, filename: str) -> bool:
        try:
            p = self._doc_path(user_id, doc_id, filename)
            doc_size = p.stat().st_size if p.exists() else 0
            if p.exists():
                p.unlink()
            await self.delete_file_hash_metadata(user_id, doc_id)

            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = max(0, int(profile.get("document_count", 0)) - 1)
                profile["storage_used"] = max(0, int(profile.get("storage_used", 0)) - int(doc_size))
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)
            return True
        except Exception as e:
            logger.error("Error deleting document %s for user %s: %s", doc_id, user_id, e)
            return False

    async def save_file_hash_metadata(self, user_id: str, document_id: str, file_metadata: Dict[str, Any]) -> bool:
        try:
            p = self._metadata_path(user_id, document_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(file_metadata, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("Error saving file metadata for %s: %s", document_id, e)
            return False

    async def get_file_hash_metadata(self, user_id: str, document_id: str) -> Optional[Dict[str, Any]]:
        try:
            p = self._metadata_path(user_id, document_id)
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Error getting file metadata for %s: %s", document_id, e)
            return None

    async def delete_file_hash_metadata(self, user_id: str, document_id: str) -> bool:
        try:
            p = self._metadata_path(user_id, document_id)
            if p.exists():
                p.unlink()
            return True
        except Exception as e:
            logger.error("Error deleting file metadata for %s: %s", document_id, e)
            return False

    async def put_bytes_by_path(self, path: str, content: bytes, content_type: str = "application/octet-stream") -> bool:
        """Write file by storage path 'container/blob'."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)

        if container != self.container_name:
            raise FileNotFoundError("Container not found")

        p = (self.base_path / container / blob).resolve()
        # Prevent path traversal
        if not str(p).startswith(str((self.base_path / container).resolve())):
            raise FileNotFoundError("Invalid path")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return True

    async def get_bytes_by_path(self, path: str) -> Tuple[bytes, str]:
        """Read file by storage path 'container/blob'. Returns (bytes, filename)."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)

        # Only allow access to our configured local container.
        if container != self.container_name:
            raise FileNotFoundError("Container not found")

        p = (self.base_path / container / blob).resolve()
        # Prevent path traversal
        if not str(p).startswith(str((self.base_path / container).resolve())):
            raise FileNotFoundError("Invalid path")
        if not p.exists() or not p.is_file():
            raise FileNotFoundError("File not found")

        return p.read_bytes(), (p.name or "download")

    async def delete_by_path(self, path: str) -> bool:
        """Delete file by storage path 'container/blob'."""
        if not path or "/" not in path:
            raise ValueError("Invalid storage path")
        container, blob = path.split("/", 1)

        if container != self.container_name:
            raise FileNotFoundError("Container not found")

        p = (self.base_path / container / blob).resolve()
        if not str(p).startswith(str((self.base_path / container).resolve())):
            raise FileNotFoundError("Invalid path")
        if not p.exists() or not p.is_file():
            raise FileNotFoundError("File not found")
        p.unlink()
        return True

    async def generate_signed_url(self, path: str, expiry_minutes: int = 5) -> Optional[str]:
        """Local storage cannot generate signed URLs; returns None to signal streaming fallback."""
        return None


# =============================================================================
# Factory
# =============================================================================


def _build_storage_service() -> Optional[StorageService]:
    stype = (settings.STORAGE_MODE or "azure").lower().strip()
    if stype == "local":
        try:
            return LocalStorageService()
        except Exception as e:
            logger.exception("Failed to initialize LocalStorageService: %s", e)
            return None
    if stype == "azure":
        try:
            if not settings.AZURE_STORAGE_ACCOUNT_NAME or not settings.AZURE_STORAGE_ACCOUNT_KEY:
                raise ValueError("STORAGE_MODE=azure requires AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY")
            connection_string = (
                "DefaultEndpointsProtocol=https;"
                f"AccountName={settings.AZURE_STORAGE_ACCOUNT_NAME};"
                f"AccountKey={settings.AZURE_STORAGE_ACCOUNT_KEY};"
                "EndpointSuffix=core.windows.net"
            )
            return AzureStorageService(
                connection_string=connection_string,
                container_name=settings.STORAGE_CONTAINER_NAME,
            )
        except Exception as e:
            logger.exception("Failed to initialize AzureStorageService (connection string): %s", e)
            return None
    if stype == "entra":
        try:
            if not settings.AZURE_STORAGE_ACCOUNT_NAME:
                raise ValueError("STORAGE_MODE=entra requires AZURE_STORAGE_ACCOUNT_NAME")
            account_url = f"https://{settings.AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
            return AzureStorageService(
                account_url=account_url,
                container_name=settings.STORAGE_CONTAINER_NAME,
            )
        except Exception as e:
            logger.exception("Failed to initialize AzureStorageService (Entra): %s", e)
            return None

    logger.warning("Unsupported STORAGE_MODE=%s; storage disabled", stype)
    return None


storage_service: Optional[StorageService] = _build_storage_service()
