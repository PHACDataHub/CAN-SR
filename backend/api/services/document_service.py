"""backend.api.services.document_service

NOTE: CAN-SR previously carried a multi-processor document service (Docling + Azure).
We are **removing Docling** and keeping only Azure Document Intelligence.

This module remains as a small compatibility wrapper for any older code paths,
but new code should prefer importing `azure_docint_client` directly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .azure_docint_client import azure_docint_client


class DocumentService:
    """Compatibility wrapper around Azure Document Intelligence only."""

    async def convert_document_to_markdown(
        self,
        source: str,
        source_type: str = "file",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not azure_docint_client or not azure_docint_client.is_available():
            return {
                "success": False,
                "error": "Azure Document Intelligence is not configured",
                "processor_used": "azure_doc_intelligence",
            }

        result = await azure_docint_client.convert_document_to_markdown(
            source, source_type=source_type, **kwargs
        )
        result["processor_used"] = "azure_doc_intelligence"
        return result

    async def get_raw_analysis_result(self, conversion_id: str) -> Optional[Dict[str, Any]]:
        if not azure_docint_client:
            return None
        return await azure_docint_client.get_raw_analysis_result(conversion_id)
