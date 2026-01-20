"""Azure Blob Storage service for user data management"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

from ..core.config import settings
from ..utils.file_hash import calculate_file_hash, create_file_metadata

logger = logging.getLogger(__name__)


class AzureStorageService:
    """Service for managing user data in Azure Blob Storage"""

    def __init__(self):
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            raise ValueError("Azure Storage connection string not configured")

        self.blob_service_client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        self.container_name = settings.AZURE_STORAGE_CONTAINER_NAME

        self._ensure_container_exists()

    def _ensure_container_exists(self):
        """Ensure the storage container exists"""
        try:
            self.blob_service_client.create_container(self.container_name)
        except Exception:
            pass

    async def create_user_directory(self, user_id: str) -> bool:
        """Create directory structure for a new user"""
        try:
            # Create user profile
            profile_data = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "document_count": 0,
                "storage_used": 0,
            }

            await self.save_user_profile(user_id, profile_data)

            # Create placeholder file to establish directory structure
            directories = [f"users/{user_id}/documents/"]

            for directory in directories:
                blob_name = f"{directory}.placeholder"
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name, blob=blob_name
                )
                blob_client.upload_blob("", overwrite=True)

            return True
        except Exception as e:
            logger.error(f"Error creating user directory for {user_id}: {e}")
            return False

    async def save_user_profile(
        self, user_id: str, profile_data: Dict[str, Any]
    ) -> bool:
        """Save user profile data"""
        try:
            blob_name = f"users/{user_id}/profile.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            profile_json = json.dumps(profile_data, indent=2)
            blob_client.upload_blob(profile_json, overwrite=True)
            return True
        except Exception as e:
            logger.error(f"Error saving user profile for {user_id}: {e}")
            return False

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile data"""
        try:
            blob_name = f"users/{user_id}/profile.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            blob_data = blob_client.download_blob().readall()
            return json.loads(blob_data.decode("utf-8"))
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting user profile for {user_id}: {e}")
            return None

    async def upload_user_document(
        self, user_id: str, filename: str, file_content: bytes
    ) -> Optional[str]:
        """Upload a document for a user with hash metadata for duplicate detection"""
        try:
            # Generate unique document ID
            doc_id = str(uuid.uuid4())
            blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"

            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            # Upload the file
            blob_client.upload_blob(file_content, overwrite=True)

            # Create and save file metadata with hash
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

            # Update user profile
            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] += 1
                profile["storage_used"] += len(file_content)
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)

            return doc_id
        except Exception as e:
            logger.error(f"Error uploading document {filename} for user {user_id}: {e}")
            return None

    async def get_user_document(
        self, user_id: str, doc_id: str, filename: str
    ) -> Optional[bytes]:
        """Get a user's document"""
        try:
            blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            return blob_client.download_blob().readall()
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting document {doc_id} for user {user_id}: {e}")
            return None

    async def list_user_documents(self, user_id: str) -> List[Dict[str, Any]]:
        """List all documents for a user - SIMPLIFIED"""
        try:
            prefix = f"users/{user_id}/documents/"
            blobs = self.blob_service_client.get_container_client(
                self.container_name
            ).list_blobs(name_starts_with=prefix)

            documents = []
            for blob in blobs:
                if not blob.name.endswith(".placeholder"):
                    # Extract doc_id and filename from blob name
                    blob_filename = blob.name.replace(prefix, "")
                    if "_" in blob_filename:
                        doc_id, filename = blob_filename.split("_", 1)

                        # Get hash metadata if available
                        hash_metadata = await self.get_file_hash_metadata(
                            user_id, doc_id
                        )

                        document_info = {
                            "document_id": doc_id,
                            "filename": filename,
                            "file_size": blob.size,
                            "upload_date": blob.last_modified.isoformat(),
                            "last_modified": blob.last_modified.isoformat(),
                        }

                        # Add hash information if available
                        if hash_metadata:
                            document_info["file_hash"] = hash_metadata.get("file_hash")
                            document_info["signature"] = hash_metadata.get("signature")

                        documents.append(document_info)

            return documents
        except Exception as e:
            logger.error(f"Error listing user documents for {user_id}: {e}")
            return []

    async def delete_user_document(
        self, user_id: str, doc_id: str, filename: str
    ) -> bool:
        """Delete a user's document"""
        try:
            # Get document size before deletion for profile update
            doc_blob_name = f"users/{user_id}/documents/{doc_id}_{filename}"
            doc_blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=doc_blob_name
            )

            # Get blob properties to determine size
            try:
                blob_properties = doc_blob_client.get_blob_properties()
                doc_size = blob_properties.size
            except ResourceNotFoundError:
                doc_size = 0

            # Delete the document
            doc_blob_client.delete_blob()

            # Delete the associated hash metadata
            await self.delete_file_hash_metadata(user_id, doc_id)

            # Update user profile
            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = max(0, profile["document_count"] - 1)
                profile["storage_used"] = max(0, profile["storage_used"] - doc_size)
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)

            return True
        except Exception as e:
            logger.error(f"Error deleting document {doc_id} for user {user_id}: {e}")
            return False

    async def calculate_user_storage_usage(self, user_id: str) -> int:
        """Calculate actual storage usage for a user"""
        try:
            prefix = f"users/{user_id}/documents/"
            blobs = self.blob_service_client.get_container_client(
                self.container_name
            ).list_blobs(name_starts_with=prefix)

            total_size = 0
            for blob in blobs:
                if not blob.name.endswith(".placeholder"):
                    total_size += blob.size or 0

            return total_size
        except Exception as e:
            logger.error(f"Error calculating storage usage for user {user_id}: {e}")
            return 0

    async def sync_user_profile_stats(self, user_id: str) -> bool:
        """Synchronize user profile statistics with actual storage"""
        try:
            documents = await self.list_user_documents(user_id)
            actual_storage = await self.calculate_user_storage_usage(user_id)

            profile = await self.get_user_profile(user_id)
            if profile:
                profile["document_count"] = len(documents)
                profile["storage_used"] = actual_storage
                profile["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self.save_user_profile(user_id, profile)
                return True
            return False
        except Exception as e:
            logger.error(f"Error syncing profile stats for user {user_id}: {e}")
            return False

    async def save_file_hash_metadata(
        self, user_id: str, document_id: str, file_metadata: Dict[str, Any]
    ) -> bool:
        """Save file hash metadata for duplicate detection"""
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            metadata_json = json.dumps(file_metadata, indent=2)
            blob_client.upload_blob(metadata_json, overwrite=True)
            return True
        except Exception as e:
            logger.error(f"Error saving file metadata for {document_id}: {e}")
            return False

    async def get_file_hash_metadata(
        self, user_id: str, document_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get file hash metadata for a specific document"""
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )

            metadata_json = blob_client.download_blob().readall().decode("utf-8")
            return json.loads(metadata_json)
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting file metadata for {document_id}: {e}")
            return None

    async def get_all_user_file_hashes(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all file hash metadata for a user for duplicate detection"""
        try:
            prefix = f"users/{user_id}/metadata/"
            blobs = self.blob_service_client.get_container_client(
                self.container_name
            ).list_blobs(name_starts_with=prefix)

            all_metadata = []
            for blob in blobs:
                if blob.name.endswith("_metadata.json"):
                    try:
                        blob_client = self.blob_service_client.get_blob_client(
                            container=self.container_name, blob=blob.name
                        )
                        metadata_json = (
                            blob_client.download_blob().readall().decode("utf-8")
                        )
                        metadata = json.loads(metadata_json)
                        all_metadata.append(metadata)
                    except Exception as e:
                        logger.warning(f"Error reading metadata from {blob.name}: {e}")
                        continue

            return all_metadata
        except Exception as e:
            logger.error(f"Error getting all file hashes for user {user_id}: {e}")
            return []

    async def delete_file_hash_metadata(self, user_id: str, document_id: str) -> bool:
        """Delete file hash metadata when document is deleted"""
        try:
            blob_name = f"users/{user_id}/metadata/{document_id}_metadata.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_name
            )
            blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            # Metadata doesn't exist, which is fine
            return True
        except Exception as e:
            logger.error(f"Error deleting file metadata for {document_id}: {e}")
            return False


# Global storage service instance
storage_service = (
    AzureStorageService() if settings.AZURE_STORAGE_CONNECTION_STRING else None
)
