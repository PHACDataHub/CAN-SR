"""
Vector Database Service using PostgreSQL and pgvector
"""

import logging
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from ..core.config import settings

logger = logging.getLogger(__name__)


def _ensure_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras as extras
        from psycopg2.extensions import register_adapter, AsIs
        import numpy as np

        def addapt_numpy_float64(numpy_float64):
            return AsIs(numpy_float64)

        def addapt_numpy_int64(numpy_int64):
            return AsIs(numpy_int64)

        def addapt_numpy_float32(numpy_float32):
            return AsIs(numpy_float32)

        def addapt_numpy_int32(numpy_int32):
            return AsIs(numpy_int32)

        def addapt_numpy_array(numpy_array):
            return AsIs(tuple(numpy_array))

        register_adapter(np.float64, addapt_numpy_float64)
        register_adapter(np.int64, addapt_numpy_int64)
        register_adapter(np.float32, addapt_numpy_float32)
        register_adapter(np.int32, addapt_numpy_int32)
        register_adapter(np.ndarray, addapt_numpy_array)

        return psycopg2, extras
    except Exception:
        raise RuntimeError("psycopg2 or numpy is not installed on the server environment")


class VectorDBService:
    def __init__(self):
        # Service is stateless; connection strings passed per-call or from settings
        self.db_conn_str = settings.POSTGRES_URI

    def _connect(self):
        """
        Connect and return a psycopg2 connection.
        Caller is responsible for closing the connection.
        """
        if not self.db_conn_str:
            raise ValueError("PostgreSQL connection string not configured")
        
        psycopg2, _ = _ensure_psycopg2()
        conn = psycopg2.connect(self.db_conn_str)
        return conn

    def ensure_schema(self) -> None:
        """
        Ensure the document_embeddings table exists in PostgreSQL.
        Also attempts to enable the vector extension.
        """
        if not self.db_conn_str:
            logger.warning("Postgres URI not set, skipping schema initialization")
            return

        conn = None
        try:
            conn = self._connect()
            cur = conn.cursor()
            
            # Enable vector extension
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            except Exception as e:
                # Might fail if not superuser, but could already be installed
                logger.warning(f"Could not enable vector extension (might already exist): {e}")
                conn.rollback()

            # Create table
            # Embedding dimension is 1536 for text-embedding-3-small and ada-002
            create_table_sql = """
                CREATE TABLE IF NOT EXISTS document_embeddings (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    content TEXT,
                    embedding vector(1536),
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                );
                
                CREATE INDEX IF NOT EXISTS idx_document_embeddings_user_id ON document_embeddings(user_id);
                CREATE INDEX IF NOT EXISTS idx_document_embeddings_document_id ON document_embeddings(document_id);
            """
            # IVFFlat index could be added later for performance on large datasets
            # CREATE INDEX ON document_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

            cur.execute(create_table_sql)
            conn.commit()
            
            logger.info("Ensured document_embeddings table exists")
            
        except Exception as e:
            logger.error(f"Failed to ensure vector db schema: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def upsert_document_embedding(
        self, 
        user_id: str, 
        document_id: str, 
        chunks: List[str], 
        embeddings: List[List[float]], 
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Insert or update document embeddings.
        Deletes existing embeddings for this document_id first to ensure clean state.
        """
        if not self.db_conn_str:
            return False

        if len(chunks) != len(embeddings):
            raise ValueError("Chunks and embeddings count must match")

        conn = None
        try:
            conn = self._connect()
            cur = conn.cursor()
            
            # 1. Delete existing embeddings for this document
            cur.execute(
                "DELETE FROM document_embeddings WHERE user_id = %s AND document_id = %s",
                (user_id, document_id)
            )
            
            # 2. Insert new embeddings
            if chunks:
                psycopg2, extras = _ensure_psycopg2()
                
                values = []
                now = datetime.now(timezone.utc)
                base_metadata = metadata or {}
                
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_id = f"{document_id}_{i}"
                    chunk_metadata = base_metadata.copy()
                    chunk_metadata["chunk_index"] = i
                    
                    values.append((
                        chunk_id,
                        user_id,
                        document_id,
                        chunk,
                        embedding,  # pgvector adapter handles list -> vector
                        json.dumps(chunk_metadata),
                        now
                    ))
                
                insert_query = """
                    INSERT INTO document_embeddings 
                    (id, user_id, document_id, content, embedding, metadata, created_at)
                    VALUES %s
                """
                
                extras.execute_values(cur, insert_query, values)
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert embeddings for doc {document_id}: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()

    def search_similar_documents(
        self, 
        user_id: str, 
        query_embedding: List[float], 
        limit: int = 5,
        threshold: float = 0.5  # Cosine distance threshold (lower is better, 0 is identical)
        # Note: Postgres vector operator <=> returns cosine distance (1 - cosine_similarity)
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents using cosine distance.
        """
        if not self.db_conn_str:
            return []

        conn = None
        try:
            conn = self._connect()
            cur = conn.cursor()
            
            # Use cosine distance operator <=>
            # Filter by user_id for security
            search_sql = """
                SELECT 
                    id, 
                    document_id, 
                    content, 
                    metadata, 
                    1 - (embedding <=> %s::vector) as similarity
                FROM document_embeddings
                WHERE user_id = %s
                ORDER BY embedding <=> %s::vector ASC
                LIMIT %s
            """
            
            # Note: We pass the embedding twice: once for calculation, once for sorting
            # But we can optimize query planning by creating the vector literal once if needed
            # For simplicity using param substitution which works fine with psycopg2 + pgvector
            
            cur.execute(search_sql, (query_embedding, user_id, query_embedding, limit))
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "id": row[0],
                    "document_id": row[1],
                    "content": row[2],
                    "metadata": row[3],
                    "similarity": float(row[4])
                })
                
            return results
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def delete_document_embeddings(self, user_id: str, document_id: str) -> bool:
        """
        Delete all embeddings for a specific document
        """
        if not self.db_conn_str:
            return False

        conn = None
        try:
            conn = self._connect()
            cur = conn.cursor()
            
            cur.execute(
                "DELETE FROM document_embeddings WHERE user_id = %s AND document_id = %s",
                (user_id, document_id)
            )
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete embeddings for doc {document_id}: {e}")
            return False
        finally:
            if conn:
                conn.close()

# Global instance
vector_db_service = VectorDBService()
