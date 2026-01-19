"""
Main Document Processing Service

This service orchestrates different document processors (Docling, Azure Document Intelligence, etc.)
and provides a unified interface for document conversion. It can automatically choose the best
processor for a given document or allow explicit processor selection.
"""

import asyncio
from typing import Dict, Any, Optional, List

from schemas.enums import ProcessorType
from .processors.docling import DoclingService
from .processors.azure_doc_intelligence.azure_doc_intelligence_service import (
    AzureDocIntelligenceService,
)


class DocumentService:
    """Main service for document processing with multiple processor support"""

    def __init__(self):
        self.docling_service = DoclingService()
        self.azure_doc_intelligence_service = AzureDocIntelligenceService()

        self.available_processors = self._check_processor_availability()

    def _check_processor_availability(self) -> Dict[str, bool]:
        """Check which processors are available"""
        return {
            ProcessorType.DOCLING.value: True,
            ProcessorType.AZURE_DOC_INTELLIGENCE.value: self.azure_doc_intelligence_service.is_available(),
        }

    async def convert_document_to_markdown(
        self,
        source: str,
        source_type: str = "file",
        processor: ProcessorType = ProcessorType.AUTO,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convert document to markdown using specified or auto-selected processor

        Args:
            source: File path or URL
            source_type: "file" or "url"
            processor: Which processor to use (auto, docling, azure_doc_intelligence)
            **kwargs: Additional processor-specific arguments

        Returns:
            Dict with conversion results including processor used
        """

        if processor == ProcessorType.AUTO:
            processor = self._auto_select_processor(source, source_type)

        if processor == ProcessorType.AZURE_DOC_INTELLIGENCE:
            if not self.available_processors[
                ProcessorType.AZURE_DOC_INTELLIGENCE.value
            ]:
                processor = ProcessorType.DOCLING
                result = await self.docling_service.convert_document_to_markdown(
                    source, source_type, **kwargs
                )
                result["processor_used"] = ProcessorType.DOCLING.value
                result["processor_fallback"] = True
                result["fallback_reason"] = "Azure Document Intelligence not available"
            else:
                result = await self.azure_doc_intelligence_service.convert_document_to_markdown(
                    source, source_type, **kwargs
                )
                result["processor_used"] = ProcessorType.AZURE_DOC_INTELLIGENCE.value

        else:
            result = await self.docling_service.convert_document_to_markdown(
                source, source_type, **kwargs
            )
            result["processor_used"] = ProcessorType.DOCLING.value

        return result

    def _auto_select_processor(self, source: str, source_type: str) -> ProcessorType:
        """
        Automatically select the best processor for the document

        Logic:
        - Default to Azure Document Intelligence for all documents
        - For specific document types that work better with Docling, use Docling
        - If Azure is not available, fall back to Docling
        """

        if not self.available_processors[ProcessorType.AZURE_DOC_INTELLIGENCE.value]:
            return ProcessorType.DOCLING

        if source_type == "file":
            source_lower = source.lower()

        return ProcessorType.AZURE_DOC_INTELLIGENCE

    async def get_processor_capabilities(self) -> Dict[str, Any]:
        """Get information about available processors and their capabilities"""
        return {
            "available_processors": self.available_processors,
            "processors": {
                ProcessorType.AZURE_DOC_INTELLIGENCE.value: {
                    "name": "Azure Document Intelligence",
                    "description": "Primary processor with superior accuracy for all document types, especially forms, tables, and structured documents",
                    "strengths": [
                        "Table extraction",
                        "Form fields",
                        "Key-value pairs",
                        "Handwriting",
                        "Figure/chart detection",
                        "General documents",
                        "Complex layouts",
                    ],
                    "features": [
                        "Markdown output",
                        "Table extraction",
                        "Figure extraction with captions",
                        "Downloadable figure images",
                        "Bounding regions",
                        "Key-value pairs",
                    ],
                    "available": self.available_processors[
                        ProcessorType.AZURE_DOC_INTELLIGENCE.value
                    ],
                },
                ProcessorType.DOCLING.value: {
                    "name": "Docling",
                    "description": "Fast and reliable fallback processor for general documents when Azure is unavailable",
                    "strengths": [
                        "Academic papers",
                        "Mixed content",
                        "Fast processing",
                        "Always available",
                    ],
                    "available": self.available_processors[ProcessorType.DOCLING.value],
                },
            },
            "auto_selection": {
                "description": "Automatically chooses the best processor based on document characteristics",
                "default_processor": ProcessorType.AZURE_DOC_INTELLIGENCE.value,
                "fallback_processor": ProcessorType.DOCLING.value,
            },
        }

    async def get_conversion_by_id(
        self, conversion_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get conversion info by ID from any processor"""

        result = await self.docling_service.get_conversion_by_id(conversion_id)
        if result:
            return result

        result = await self.azure_doc_intelligence_service.get_conversion_by_id(
            conversion_id
        )
        if result:
            return result

        return None

    async def get_markdown_content(
        self, conversion_id: str, processor_used: Optional[str] = None
    ) -> Optional[str]:
        """
        Get markdown content by conversion ID from the specific processor that was used

        Args:
            conversion_id: The conversion ID to retrieve content for
            processor_used: The processor that was used (if known) - improves efficiency
        """

        # If we know which processor was used, check that one first
        if processor_used:
            if processor_used == ProcessorType.AZURE_DOC_INTELLIGENCE.value:
                content = (
                    await self.azure_doc_intelligence_service.get_markdown_content(
                        conversion_id
                    )
                )
                if content:
                    return content
            elif processor_used == ProcessorType.DOCLING.value:
                content = await self.docling_service.get_markdown_content(conversion_id)
                if content:
                    return content

        # Fallback: Try both processors (for backward compatibility or if processor_used is unknown)
        # Check Azure first since it's our default
        content = await self.azure_doc_intelligence_service.get_markdown_content(
            conversion_id
        )
        if content:
            return content

        content = await self.docling_service.get_markdown_content(conversion_id)
        if content:
            return content

        return None

    async def get_figures_for_conversion(
        self, conversion_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all figures metadata for a specific conversion

        This method works for conversions processed with either Docling or Azure Document Intelligence

        Args:
            conversion_id: The conversion ID

        Returns:
            List of figure metadata dictionaries or None if not found
        """
        # Try Docling first
        figures = await self.docling_service.get_figures_for_conversion(conversion_id)
        if figures is not None:
            return figures

        # Try Azure Document Intelligence
        figures = await self.azure_doc_intelligence_service.get_figures_for_conversion(
            conversion_id
        )
        if figures is not None:
            return figures

        return None

    async def get_raw_analysis_result(
        self, conversion_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the complete raw analysis result with ALL bounding boxes

        This is available for documents processed with either Azure Document Intelligence or Docling.
        The raw analysis includes all detected elements with their bounding box coordinates:

        Azure DI provides:
        - Pages with words, lines, selection marks
        - Paragraphs with roles and bounding regions
        - Tables with cells and bounding boxes
        - Figures with bounding regions and captions
        - Sections and structural information

        Docling provides:
        - Pages with dimensions
        - Text items (paragraphs) with bounding regions and roles
        - Tables with cells and bounding boxes
        - Pictures/figures with bounding regions
        - Document structure (body, furniture, groups)

        Args:
            conversion_id: The conversion ID

        Returns:
            Complete analysis result dictionary or None if not found
        """
        # Try Azure Document Intelligence first
        result = await self.azure_doc_intelligence_service.get_raw_analysis_result(
            conversion_id
        )
        if result:
            return result

        # Try Docling
        result = await self.docling_service.get_raw_analysis_result(conversion_id)
        if result:
            return result

        return None
