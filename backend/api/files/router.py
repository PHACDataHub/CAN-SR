"""
Files router for document management in CAN-SR.
"""
from typing import List, Dict, Any, Optional
import os
import logging
from datetime import datetime, timezone
from azure.core.exceptions import ResourceNotFoundError

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.security import get_current_active_user
from ..core.config import settings
from ..services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


class DocumentUploadResponse(BaseModel):
    """Response model for document upload"""
    document_id: str
    filename: str
    file_size: int
    upload_status: str
    message: str


class DocumentInfo(BaseModel):
    """Document information model"""
    document_id: str
    filename: str
    file_size: int
    upload_date: str


class DocumentListResponse(BaseModel):
    """Response model for document list"""
    total_documents: int
    documents: List[DocumentInfo]


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Upload a document for the user
    """
    try:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required"
            )

        file_content = await file.read()

        if not storage_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service not available",
            )

        document_id = await storage_service.upload_user_document(
            user_id=current_user["id"],
            filename=file.filename,
            file_content=file_content,
        )

        if not document_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload document",
            )

        return DocumentUploadResponse(
            document_id=document_id,
            filename=file.filename,
            file_size=len(file_content),
            upload_status="completed",
            message="Document uploaded successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading document: {str(e)}",
        )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    List all documents owned by the current user
    """
    try:
        if not storage_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service not available",
            )

        user_documents = await storage_service.list_user_documents(current_user["id"])

        document_infos = []
        for doc in user_documents:
            document_info = DocumentInfo(
                document_id=doc["document_id"],
                filename=doc["filename"],
                file_size=doc["file_size"],
                upload_date=doc["upload_date"],
            )
            document_infos.append(document_info)

        return DocumentListResponse(
            total_documents=len(document_infos),
            documents=document_infos
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing documents: {str(e)}",
        )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Download a document by its ID
    """
    try:
        if not storage_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service not available",
            )

        documents = await storage_service.list_user_documents(current_user["id"])
        document = next(
            (doc for doc in documents if doc["document_id"] == document_id), None
        )

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        file_content = await storage_service.get_user_document(
            current_user["id"], document_id, document["filename"]
        )

        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document content not found",
            )

        def generate():
            yield file_content

        return StreamingResponse(
            generate(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={document['filename']}"
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading document: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading document: {str(e)}",
        )


@router.get("/download-by-path")
async def download_by_path(
    path: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Stream a blob directly by storage path in the form 'container/blob_path'
    Example storage_path: "container/users/123/docid_filename.pdf"
    """
    try:
        if not storage_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service not available",
            )

        # Basic validation: expect "container/blob"
        if not path or "/" not in path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Invalid storage path"
            )

        container, blob = path.split("/", 1)
        logger.info(f"Downloading blob: container={container}, blob={blob}")

        try:
            blob_client = storage_service.blob_service_client.get_blob_client(
                container=container, blob=blob
            )
            stream = blob_client.download_blob()
            content = stream.readall()
        except ResourceNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Blob not found"
            )

        filename = os.path.basename(blob) or "download"
        
        def gen():
            yield content

        return StreamingResponse(
            gen(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading blob: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading blob: {str(e)}",
        )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Delete a document
    """
    try:
        if not storage_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service not available",
            )

        documents = await storage_service.list_user_documents(current_user["id"])
        document = next(
            (doc for doc in documents if doc["document_id"] == document_id), None
        )

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        success = await storage_service.delete_user_document(
            current_user["id"], document_id, document["filename"]
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete document",
            )

        return {
            "message": "Document deleted successfully",
            "document_id": document_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting document: {str(e)}",
        )
