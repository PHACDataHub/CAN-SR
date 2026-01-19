"""
File hash utilities for duplicate detection
"""

import hashlib
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


def calculate_file_hash(file_content: bytes) -> str:
    """
    Calculate SHA-256 hash of file content for duplicate detection

    Args:
        file_content: The raw bytes of the file

    Returns:
        str: Hexadecimal SHA-256 hash of the file content
    """
    try:
        sha256_hash = hashlib.sha256()
        sha256_hash.update(file_content)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating file hash: {e}")
        raise


def calculate_file_signature(filename: str, file_size: int, file_hash: str) -> str:
    """
    Generate a unique signature combining filename, size, and hash

    Args:
        filename: Original filename
        file_size: File size in bytes
        file_hash: SHA-256 hash of file content

    Returns:
        str: Combined signature for quick lookups
    """
    return f"{filename.lower()}_{file_size}_{file_hash[:16]}"


def create_file_metadata(
    filename: str, file_content: bytes, additional_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Create comprehensive file metadata including hash for duplicate detection

    Args:
        filename: Original filename
        file_content: Raw file bytes
        additional_metadata: Optional additional metadata to include

    Returns:
        Dict containing file metadata with hash information
    """
    try:
        file_hash = calculate_file_hash(file_content)
        file_size = len(file_content)

        metadata = {
            "filename": filename,
            "file_size": file_size,
            "file_hash": file_hash,
            "signature": calculate_file_signature(filename, file_size, file_hash),
        }

        if additional_metadata:
            metadata.update(additional_metadata)

        return metadata

    except Exception as e:
        logger.error(f"Error creating file metadata for {filename}: {e}")
        raise


def compare_file_hashes(hash1: str, hash2: str) -> bool:
    """
    Compare two file hashes for equality

    Args:
        hash1: First file hash
        hash2: Second file hash

    Returns:
        bool: True if hashes match (files are identical)
    """
    return hash1.lower() == hash2.lower()


def is_duplicate_by_hash(new_file_hash: str, existing_hashes: list) -> tuple[bool, str]:
    """
    Check if a file hash matches any existing hashes

    Args:
        new_file_hash: Hash of the new file
        existing_hashes: List of existing file hashes

    Returns:
        tuple: (is_duplicate: bool, matching_hash: str or None)
    """
    for existing_hash in existing_hashes:
        if compare_file_hashes(new_file_hash, existing_hash):
            return True, existing_hash

    return False, None


def get_duplicate_info(
    file_metadata: Dict[str, Any], existing_files: list
) -> Dict[str, Any]:
    """
    Get detailed information about potential duplicates

    Args:
        file_metadata: Metadata of the new file
        existing_files: List of existing file metadata dictionaries

    Returns:
        Dict containing duplicate detection results
    """
    new_hash = file_metadata.get("file_hash")
    if not new_hash:
        return {"is_duplicate": False, "duplicate_files": []}

    duplicate_files = []

    for existing_file in existing_files:
        existing_hash = existing_file.get("file_hash")
        if existing_hash and compare_file_hashes(new_hash, existing_hash):
            duplicate_files.append(
                {
                    "document_id": existing_file.get("document_id"),
                    "filename": existing_file.get("filename"),
                    "file_size": existing_file.get("file_size"),
                    "upload_date": existing_file.get("upload_date"),
                    "file_hash": existing_hash,
                }
            )

    return {
        "is_duplicate": len(duplicate_files) > 0,
        "duplicate_count": len(duplicate_files),
        "duplicate_files": duplicate_files,
        "new_file_hash": new_hash,
    }
