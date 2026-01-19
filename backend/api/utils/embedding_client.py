import logging
import os
import asyncio
from typing import Dict, List, Any, cast
from datetime import datetime

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# Performance optimization settings
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "512"))
EMBEDDING_TIMEOUT = float(
    os.getenv("EMBEDDING_TIMEOUT", "120.0")
)  # Increased timeout for larger batches
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_EMBEDDING_REQUESTS", "4"))


class EmbeddingClient:
    """
    Optimized client for communicating with the BGE-M3 embedding service.
    Supports batch processing and concurrent requests for better GPU utilization.
    """

    def __init__(self):
        self.embedding_service_url = settings.EMBEDDING_SERVICE_URL
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def embed_query(
        self, query: str, return_dense: bool = True, return_sparse: bool = True
    ) -> Dict[str, Any]:
        """
        Get both dense and sparse embedding for a single query.
        Returns dict with 'dense_embedding' and 'sparse_embedding' keys.
        """
        try:
            async with self.semaphore:
                async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
                    response = await client.post(
                        f"{self.embedding_service_url}/embed_query",
                        json={
                            "query": query,
                            "return_dense": return_dense,
                            "return_sparse": return_sparse,
                        },
                    )
                    response.raise_for_status()
                    return response.json()
        except Exception as e:
            logger.error(f"Query embedding failed: {str(e)}")
            raise Exception(f"Query embedding failed: {str(e)}")

    async def embed_texts(
        self, texts: List[str], return_dense: bool = True, return_sparse: bool = True
    ) -> Dict[str, Any]:
        """
        Get both dense and sparse embeddings for a list of texts with optimized batch processing.
        Returns dict with 'dense_embeddings' and 'sparse_embeddings' keys.
        """
        if not texts:
            return {"dense_embeddings": [], "sparse_embeddings": []}

        # Use optimized batch processing for large text lists
        if len(texts) > EMBEDDING_BATCH_SIZE:
            return await self._embed_texts_batched(texts, return_dense, return_sparse)
        else:
            return await self._embed_texts_single_request(
                texts, return_dense, return_sparse
            )

    async def _embed_texts_single_request(
        self, texts: List[str], return_dense: bool = True, return_sparse: bool = True
    ) -> Dict[str, Any]:
        """Handle single request for smaller text lists"""
        try:
            async with self.semaphore:
                async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
                    response = await client.post(
                        f"{self.embedding_service_url}/embed",
                        json={
                            "texts": texts,
                            "return_dense": return_dense,
                            "return_sparse": return_sparse,
                        },
                    )
                    response.raise_for_status()
                    return response.json()
        except Exception as e:
            logger.error(f"Text embedding failed: {str(e)}")
            raise Exception(f"Text embedding failed: {str(e)}")

    async def _embed_texts_batched(
        self, texts: List[str], return_dense: bool = True, return_sparse: bool = True
    ) -> Dict[str, Any]:
        """Handle large text lists with optimized batching for better GPU utilization"""
        start_time = datetime.now()
        logger.info(
            f"Processing {len(texts)} texts in batches of {EMBEDDING_BATCH_SIZE}"
        )

        # Split texts into batches
        batches = [
            texts[i : i + EMBEDDING_BATCH_SIZE]
            for i in range(0, len(texts), EMBEDDING_BATCH_SIZE)
        ]

        logger.info(f"Created {len(batches)} batches for processing")

        # Process batches concurrently
        async def process_batch(batch_texts):
            return await self._embed_texts_single_request(
                batch_texts, return_dense, return_sparse
            )

        try:
            # Process all batches concurrently with semaphore control
            batch_results = await asyncio.gather(
                *[process_batch(batch) for batch in batches], return_exceptions=True
            )

            # Combine results
            combined_dense = []
            combined_sparse = []

            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Batch {i} failed: {result}")
                    raise result

                # At this point, result is guaranteed to be a dict, not an exception
                # Use type cast to help the type checker understand this
                result_dict = cast(Dict[str, Any], result)

                if return_dense and "dense_embeddings" in result_dict:
                    combined_dense.extend(result_dict["dense_embeddings"])

                if return_sparse and "sparse_embeddings" in result_dict:
                    combined_sparse.extend(result_dict["sparse_embeddings"])

            total_time = (datetime.now() - start_time).total_seconds()
            throughput = len(texts) / total_time if total_time > 0 else 0
            logger.info(
                f"Batch embedding completed: {len(texts)} texts in {total_time:.2f}s ({throughput:.1f} texts/sec)"
            )

            return {
                "dense_embeddings": combined_dense,
                "sparse_embeddings": combined_sparse,
            }

        except Exception as e:
            logger.error(f"Batch embedding failed: {str(e)}")
            raise Exception(f"Batch embedding failed: {str(e)}")


# Create a singleton instance
embedding_client = EmbeddingClient()
