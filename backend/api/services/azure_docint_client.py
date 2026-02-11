"""
Azure Document Intelligence Service for PDF processing

This service uses Azure's Document Intelligence to extract
structured content from PDF documents. It provides an alternative to Docling for
document processing with potentially better handling of complex layouts, tables,
and structured documents.

Key Features:
- Superior table extraction
- Form field recognition
- Multi-language support
- Layout analysis with reading order
- Handwriting recognition
- Key-value pair extraction
- Figure/chart detection and extraction with captions
- Downloadable cropped figure images
"""

import base64
import os
import uuid
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from bs4 import BeautifulSoup
from typing import TYPE_CHECKING

try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential

    AZURE_DOC_INTELLIGENCE_AVAILABLE = True
except ImportError:
    AZURE_DOC_INTELLIGENCE_AVAILABLE = False
    # Keep type names defined so type annotations don't crash at runtime when SDK isn't installed.
    from typing import Any as DocumentIntelligenceClient  # type: ignore
    from typing import Any as AnalyzeDocumentRequest  # type: ignore
    from typing import Any as AzureKeyCredential  # type: ignore
    print(
        "Azure Document Intelligence SDK not installed. Install with: pip install azure-ai-documentintelligence azure-core"
    )


class AzureDocIntelligenceService:
    """Service for processing documents using Azure Document Intelligence"""

    def __init__(self):
        self.base_path = Path(__file__).parent.parent.parent.parent.parent
        # Unified directory structure: output/azure_doc_intelligence/{conversion_id}/
        self.output_base_dir = self.base_path / "output" / "azure_doc_intelligence"
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Azure client
        self.client = self._init_client()

    def _init_client(self) -> Optional["DocumentIntelligenceClient"]:
        """Initialize Azure Document Intelligence client"""
        if not AZURE_DOC_INTELLIGENCE_AVAILABLE:
            return None

        endpoint = os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT")
        key = os.getenv("AZURE_DOC_INTELLIGENCE_KEY")

        if not endpoint or not key:
            print(
                "Azure Document Intelligence credentials not found. Set AZURE_DOC_INTELLIGENCE_ENDPOINT and AZURE_DOC_INTELLIGENCE_KEY"
            )
            return None

        try:
            return DocumentIntelligenceClient(
                endpoint=endpoint, credential=AzureKeyCredential(key)
            )
        except Exception as e:
            print(f"Failed to initialize Azure Document Intelligence client: {e}")
            return None

    def _analyze_document_sync(
        self, source: str, source_type: str, output_param: Optional[List[str]]
    ):
        """Synchronous wrapper for document analysis to run in thread pool"""
        if source_type == "file":
            with open(source, "rb") as f:
                file_content = f.read()
            # Use the correct API format
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-layout",
                body=file_content,
                content_type="application/octet-stream",
                output_content_format="markdown",
                output=output_param,
            )
        else:  # URL
            # For URL, use AnalyzeDocumentRequest
            analyze_request = AnalyzeDocumentRequest(url_source=source)
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-layout",
                analyze_request=analyze_request,
                output_content_format="markdown",
                output=output_param,
            )

        # Wait for completion (this is the blocking part)
        result = poller.result()

        # Extract result_id from the poller
        result_id = None
        try:
            # Extract result_id from operation-location header in initial response
            if hasattr(poller, "_polling_method") and hasattr(
                poller._polling_method, "_initial_response"
            ):
                initial_resp = poller._polling_method._initial_response
                if hasattr(initial_resp, "http_response") and hasattr(
                    initial_resp.http_response, "headers"
                ):
                    headers = initial_resp.http_response.headers
                    # Try different header names (Azure API uses 'operation-location')
                    for header_name in [
                        "operation-location",
                        "Operation-Location",
                    ]:
                        if header_name in headers:
                            operation_location = headers[header_name]
                            # Extract result_id from URL: .../analyzeResults/{result_id}?api-version=...
                            if "analyzeResults" in operation_location:
                                result_id = operation_location.split("/")[-1].split(
                                    "?"
                                )[0]
                                break
        except Exception as e:
            print(f"Warning: Could not extract result_id: {str(e)}")

        return result, result_id

    async def convert_document_to_markdown(
        self,
        source: str,
        source_type: str = "file",
        extract_figures: bool = True,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Convert document to markdown using Azure Document Intelligence (Non-blocking)

        Args:
            source: File path or URL to the document
            source_type: Type of source ("file" or "url")
            extract_figures: Whether to extract figures
            output_dir: Optional output directory. If provided, saves directly here.
                        If None, uses legacy UUID-based path in output/azure_doc_intelligence/
        """
        return await asyncio.to_thread(
            self._convert_document_sync,
            source,
            source_type,
            extract_figures,
            output_dir,
        )

    def _convert_document_sync(
        self,
        source: str,
        source_type: str = "file",
        extract_figures: bool = True,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous implementation of document conversion

        Args:
            output_dir: If provided, save output directly to this directory.
                        If None, uses legacy UUID-based path.
        """
        if not self.client:
            return {
                "success": False,
                "error": "Azure Document Intelligence client not available",
                "conversion_id": str(uuid.uuid4()),
            }

        conversion_id = str(uuid.uuid4())
        start_time = datetime.now()

        try:
            # Use provided output_dir or fall back to legacy UUID-based path
            if output_dir:
                conversion_dir = output_dir
                conversion_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Legacy: output/azure_doc_intelligence/{conversion_id}/
                conversion_dir = self.output_base_dir / conversion_id
                conversion_dir.mkdir(parents=True, exist_ok=True)

            # Define all file paths within the conversion directory
            log_path = conversion_dir / "conversion.log"
            raw_json_path = conversion_dir / "raw_analysis.json"
            markdown_path = conversion_dir / "document.md"
            metadata_path = conversion_dir / "metadata.json"
            figures_dir = conversion_dir / "figures"

            self._log_sync(
                log_path, f"Starting Azure Document Intelligence conversion: {source}"
            )

            # Analyze document - Updated API format
            # Include 'figures' in output if extract_figures is True
            output_param = ["figures"] if extract_figures else None

            self._log_sync(
                log_path, "Document analysis started (in background thread)..."
            )

            # Run the blocking analysis directly since we are already in a thread
            result, result_id = self._analyze_document_sync(
                source,
                source_type,
                output_param,
            )

            self._log_sync(log_path, "Document analysis completed")

            # Convert full result to dictionary for JSON serialization (with ALL bounding boxes)
            result_dict = result.as_dict()

            # Add processor field for format detection
            result_dict["processor"] = "azure_doc_intelligence"

            # Save the FULL raw JSON response
            with open(raw_json_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)
            self._log_sync(
                log_path,
                f"Saved full raw JSON with bounding boxes to raw_analysis.json",
            )

            # Extract markdown content
            markdown_content = result.content if result.content else ""

            # Save markdown
            with open(markdown_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            # Extract and save tables as separate HTML files
            self._extract_and_save_tables_sync(
                result=result,
                conversion_dir=conversion_dir,
                markdown_content=markdown_content,
                log_path=log_path,
            )

            # Process figures if requested
            figures_metadata = []

            if extract_figures and result.figures:
                figures_dir.mkdir(parents=True, exist_ok=True)
                self._log_sync(
                    log_path, f"Found {len(result.figures)} figures to process"
                )

                if result_id:
                    self._log_sync(
                        log_path,
                        f"Extracted result_id: {result_id}",
                    )
                else:
                    self._log_sync(
                        log_path,
                        "⚠️ Could not extract result_id - figure images will not be downloaded",
                    )

                for idx, figure in enumerate(result.figures):
                    figure_id = (
                        figure.id
                        if hasattr(figure, "id") and figure.id
                        else f"unknown_{idx}"
                    )

                    # Extract figure metadata
                    figure_info = {
                        "id": figure_id,
                        "page": (
                            figure.bounding_regions[0].page_number
                            if figure.bounding_regions
                            else None
                        ),
                        "caption": (
                            figure.caption.content
                            if hasattr(figure, "caption") and figure.caption
                            else None
                        ),
                        "spans": (
                            [
                                {"offset": span.offset, "length": span.length}
                                for span in figure.spans
                            ]
                            if figure.spans
                            else []
                        ),
                        "bounding_regions": (
                            [
                                {
                                    "page_number": region.page_number,
                                    "polygon": region.polygon,
                                }
                                for region in figure.bounding_regions
                            ]
                            if figure.bounding_regions
                            else []
                        ),
                    }

                    # Download the figure image if we have a result_id
                    if result_id:
                        image_path = self._download_figure_sync(
                            result_id=result_id,
                            figure_id=figure_id,
                            figures_dir=figures_dir,
                            log_path=log_path,
                        )
                        if image_path:
                            figure_info["image_path"] = image_path
                    else:
                        self._log_sync(
                            log_path,
                            f"Skipping image download for figure {figure_id} (no result_id)",
                        )

                    figures_metadata.append(figure_info)

                self._log_sync(log_path, f"Processed {len(figures_metadata)} figures")

            # Create metadata
            end_time = datetime.now()
            conversion_time = (end_time - start_time).total_seconds()

            metadata = {
                "conversion_id": conversion_id,
                "source": source,
                "source_type": source_type,
                "processor": "azure_doc_intelligence",
                "model_id": "prebuilt-layout",
                "status": "success",
                "conversion_dir": str(conversion_dir),
                "markdown_path": str(markdown_path),
                "raw_json_path": str(raw_json_path),
                "log_path": str(log_path),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "conversion_time": conversion_time,
                "content_length": len(markdown_content),
                "page_count": len(result.pages) if result.pages else 0,
                "tables_found": len(result.tables) if result.tables else 0,
                "key_value_pairs_found": (
                    len(result.key_value_pairs) if result.key_value_pairs else 0
                ),
                "figures_found": len(figures_metadata),
                "figures": figures_metadata,
            }

            # Save metadata
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            self._log_sync(
                log_path, f"Conversion completed successfully in {conversion_time:.2f}s"
            )
            self._log_sync(log_path, f"Pages processed: {metadata['page_count']}")
            self._log_sync(log_path, f"Tables found: {metadata['tables_found']}")
            self._log_sync(
                log_path, f"Key-value pairs found: {metadata['key_value_pairs_found']}"
            )
            self._log_sync(log_path, f"Figures found: {metadata['figures_found']}")

            return {
                "success": True,
                "conversion_id": conversion_id,
                "markdown_path": str(markdown_path),
                "metadata": {
                    "content_length": len(markdown_content),
                    "conversion_time": conversion_time,
                    "page_count": metadata["page_count"],
                    "tables_found": metadata["tables_found"],
                    "key_value_pairs_found": metadata["key_value_pairs_found"],
                    "figures_found": metadata["figures_found"],
                    "figures": figures_metadata,
                },
            }

        except Exception as e:
            error_msg = f"Azure Document Intelligence conversion failed: {str(e)}"

            # Try to log error if log_path was created
            try:
                self._log_sync(log_path, f"ERROR: {error_msg}")
            except:
                pass

            # Save error metadata
            metadata = {
                "conversion_id": conversion_id,
                "source": source,
                "source_type": source_type,
                "processor": "azure_doc_intelligence",
                "status": "error",
                "error": error_msg,
                "conversion_dir": (
                    str(conversion_dir) if "conversion_dir" in locals() else None
                ),
                "log_path": str(log_path) if "log_path" in locals() else None,
                "start_time": start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
            }

            # Save metadata to conversion directory if it exists
            try:
                if "metadata_path" in locals():
                    with open(metadata_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2)
            except:
                pass

            return {
                "success": False,
                "error": error_msg,
                "conversion_id": conversion_id,
            }

    async def _log(self, log_path: Path, message: str):
        """Write log message (Async wrapper)"""
        await asyncio.to_thread(self._log_sync, log_path, message)

    def _log_sync(self, log_path: Path, message: str):
        """Write log message (Synchronous)"""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {message}\n"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)

    def _extract_and_save_tables_sync(
        self,
        result: Any,
        conversion_dir: Path,
        markdown_content: str,
        log_path: Path,
    ) -> None:
        """
        Extract tables from Azure result and save as separate HTML files

        Args:
            result: Azure Document Intelligence result
            conversion_dir: Conversion directory
            markdown_content: The markdown content containing HTML tables
            log_path: Log file path
        """
        import re

        if not result.tables or len(result.tables) == 0:
            self._log_sync(log_path, "No tables found in document")
            return

        # Create tables directory
        tables_dir = conversion_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)

        self._log_sync(log_path, f"Found {len(result.tables)} tables to extract")

        # Extract HTML tables from markdown content using regex
        # Match <table>...</table> blocks
        table_pattern = r"<table>.*?</table>"
        html_tables = re.findall(table_pattern, markdown_content, re.DOTALL)

        # Save each table as a separate HTML file
        for idx, html_table in enumerate(html_tables, start=1):
            try:
                table_html_path = tables_dir / f"table-{idx}.html"
                with open(table_html_path, "w", encoding="utf-8") as f:
                    f.write(html_table)
                self._log_sync(log_path, f"Saved table {idx} to {table_html_path.name}")
            except Exception as e:
                self._log_sync(log_path, f"Failed to save table {idx}: {str(e)}")

        self._log_sync(
            log_path, f"Extracted {len(html_tables)} tables to tables/ directory"
        )

    def _download_figure_sync(
        self, result_id: str, figure_id: str, figures_dir: Path, log_path: Path
    ) -> Optional[str]:
        """
        Download a single figure image from Azure Document Intelligence

        Args:
            result_id: The analysis result ID
            figure_id: The figure ID (e.g., "1.1" for page 1, figure 1)
            figures_dir: Directory to save the figure
            log_path: Log file path

        Returns:
            Relative path to the saved figure or None if failed
        """
        try:
            # Get the figure using the SDK's get_analyze_result_figure method
            figure_stream = self.client.get_analyze_result_figure(
                model_id="prebuilt-layout", result_id=result_id, figure_id=figure_id
            )

            # Save the figure
            figure_filename = f"{figure_id}.png"
            figure_path = figures_dir / figure_filename

            with open(figure_path, "wb") as f:
                for chunk in figure_stream:
                    f.write(chunk)

            self._log_sync(
                log_path, f"Downloaded figure {figure_id} to {figure_filename}"
            )
            return f"figures/{figure_filename}"

        except Exception as e:
            self._log_sync(log_path, f"Failed to download figure {figure_id}: {str(e)}")
            return None

    async def get_conversion_by_id(
        self, conversion_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get conversion metadata by ID"""
        metadata_path = self.output_base_dir / conversion_id / "metadata.json"

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    async def get_markdown_content(self, conversion_id: str) -> Optional[str]:
        """
        Get markdown content by conversion ID for LLM entity extraction

        Returns the markdown content from document.md
        """
        conversion_dir = self.output_base_dir / conversion_id

        markdown_path = conversion_dir / "document.md"
        if not markdown_path.exists():
            return None

        try:
            with open(markdown_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def is_available(self) -> bool:
        """Check if Azure Document Intelligence is available and configured"""
        return AZURE_DOC_INTELLIGENCE_AVAILABLE and self.client is not None

    async def get_figures_for_conversion(
        self, conversion_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all figures metadata for a specific conversion

        Args:
            conversion_id: The conversion ID

        Returns:
            List of figure metadata dictionaries or None if not found
        """
        metadata = await self.get_conversion_by_id(conversion_id)
        if metadata and "figures" in metadata:
            return metadata["figures"]
        return None

    async def get_raw_analysis_result(
        self, conversion_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the complete raw JSON analysis result with ALL bounding boxes

        This includes:
        - All pages with words, lines, spans, selection marks
        - All paragraphs with bounding regions and roles
        - All tables with cells and bounding boxes
        - All figures with bounding regions
        - All sections and structural information

        Args:
            conversion_id: The conversion ID

        Returns:
            Complete analysis result dictionary or None if not found
        """
        raw_json_path = self.output_base_dir / conversion_id / "raw_analysis.json"

        if not raw_json_path.exists():
            return None

        try:
            with open(raw_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # CAN-SR helpers (artifacts for citations)
    # ------------------------------------------------------------------

    @staticmethod
    def _html_table_to_markdown(html_table: str) -> str:
        """Convert a single <table>...</table> block into GitHub-flavored markdown.

        Best-effort conversion for prompt inclusion.
        """
        soup = BeautifulSoup(html_table, "html.parser")
        table = soup.find("table")
        if not table:
            return html_table

        rows: List[List[str]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            row = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
            if row:
                rows.append(row)

        if not rows:
            return ""

        # Normalize row widths
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]

        header = rows[0]
        body = rows[1:] if len(rows) > 1 else []

        def esc(v: str) -> str:
            return (v or "").replace("|", "\\|")

        md_lines = [
            "| " + " | ".join(esc(x) for x in header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        for r in body:
            md_lines.append("| " + " | ".join(esc(x) for x in r) + " |")
        return "\n".join(md_lines)

    @staticmethod
    def _extract_html_tables_from_markdown(markdown: str) -> List[str]:
        """Extract <table> blocks from Azure markdown content."""
        import re

        if not markdown:
            return []
        table_pattern = r"<table>.*?</table>"
        return re.findall(table_pattern, markdown, re.DOTALL)

    def _download_figure_bytes_sync(self, result_id: str, figure_id: str) -> Optional[bytes]:
        """Download a single figure image from Azure DI as bytes (sync)."""
        try:
            stream = self.client.get_analyze_result_figure(
                model_id="prebuilt-layout", result_id=result_id, figure_id=figure_id
            )
            chunks: List[bytes] = []
            for chunk in stream:
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception:
            return None

    async def extract_citation_artifacts(
        self,
        source_pdf: str,
        source_type: str = "file",
    ) -> Dict[str, Any]:
        """Run Azure DI and return citation-ready figure/table artifacts.

        Returns:
          {
            "success": bool,
            "error": str|None,
            "raw_analysis": dict|None,
            "figures": [
               {"index": 1, "azure_id": "1.1", "caption": str|None, "bounding_box": {...}, "png_bytes": bytes}
            ],
            "tables": [
               {"index": 1, "caption": None, "bounding_box": {...}, "table_markdown": "|...|"}
            ]
          }

        Notes:
        - `description` is intentionally not generated here.
        - Bounding boxes are stored as Azure DI polygon regions.
        """

        if not self.client:
            return {"success": False, "error": "Azure Document Intelligence client not available"}

        # We need figures in output.
        output_param = ["figures"]

        try:
            result, result_id = await asyncio.to_thread(
                self._analyze_document_sync, source_pdf, source_type, output_param
            )
        except Exception as e:
            return {"success": False, "error": f"Azure DI analyze failed: {e}"}

        raw_analysis = result.as_dict() if hasattr(result, "as_dict") else {}
        raw_analysis["processor"] = "azure_doc_intelligence"

        # Preserve page-level metadata so callers can normalize polygons into
        # the same coordinate system as Grobid TEI coords.
        # Typical shape: {pageNumber,width,height,unit}
        pages_meta = raw_analysis.get("pages") or []

        markdown_content = getattr(result, "content", None) or ""

        # -----------------
        # Tables
        # -----------------
        html_tables = self._extract_html_tables_from_markdown(markdown_content)
        md_tables: List[str] = [self._html_table_to_markdown(t) for t in html_tables]

        # Azure gives table bounding regions under raw_analysis['tables'][*]['boundingRegions']
        raw_tables = raw_analysis.get("tables", []) or []

        tables_out: List[Dict[str, Any]] = []
        for i, md in enumerate(md_tables, start=1):
            bbox = None
            if i - 1 < len(raw_tables):
                bbox = raw_tables[i - 1].get("boundingRegions") or raw_tables[i - 1].get("bounding_regions")
            tables_out.append(
                {
                    "index": i,
                    "caption": None,
                    "bounding_box": bbox,
                    "table_markdown": md,
                }
            )

        # -----------------
        # Figures
        # -----------------
        figures_out: List[Dict[str, Any]] = []
        raw_figures = raw_analysis.get("figures", []) or []

        # Prefer SDK figures list for caption/bbox, but fall back to raw dict.
        sdk_figures = getattr(result, "figures", None) or []
        for idx, fig in enumerate(sdk_figures, start=1):
            azure_id = getattr(fig, "id", None) or f"unknown_{idx}"
            caption = None
            try:
                cap = getattr(fig, "caption", None)
                caption = getattr(cap, "content", None) if cap else None
            except Exception:
                caption = None

            bounding_regions = []
            try:
                for region in (getattr(fig, "bounding_regions", None) or []):
                    bounding_regions.append(
                        {"page_number": region.page_number, "polygon": region.polygon}
                    )
            except Exception:
                bounding_regions = []

            png_bytes = None
            if result_id:
                png_bytes = await asyncio.to_thread(self._download_figure_bytes_sync, result_id, azure_id)

            if not png_bytes:
                # If we couldn't download, skip storing bytes (still return metadata)
                png_bytes = b""

            figures_out.append(
                {
                    "index": idx,
                    "azure_id": azure_id,
                    "caption": caption,
                    "bounding_box": bounding_regions,
                    "png_bytes": png_bytes,
                }
            )

        # If SDK did not return figures but raw JSON did, include raw ones.
        if not figures_out and raw_figures:
            for idx, fig in enumerate(raw_figures, start=1):
                figures_out.append(
                    {
                        "index": idx,
                        "azure_id": fig.get("id") or f"raw_{idx}",
                        "caption": (fig.get("caption", {}) or {}).get("content") if isinstance(fig.get("caption"), dict) else None,
                        "bounding_box": fig.get("boundingRegions") or fig.get("bounding_regions"),
                        "png_bytes": b"",
                    }
                )

        return {
            "success": True,
            "raw_analysis": raw_analysis,
            "pages": pages_meta,
            "figures": figures_out,
            "tables": tables_out,
        }


# Global instance for routers/services
try:
    azure_docint_client = AzureDocIntelligenceService()
except Exception:
    azure_docint_client = None  # type: ignore