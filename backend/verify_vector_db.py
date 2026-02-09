
import asyncio
import os
import random
import uuid
import sys
from datetime import datetime

# Add current directory to path so we can import from api
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv()

# Set dummy env vars for required settings to bypass validation if not set
required_vars = [
    "DATABRICKS_INSTANCE", "DATABRICKS_TOKEN", 
    "JOB_ID_EUROPEPMC", "JOB_ID_PUBMED", "JOB_ID_SCOPUS",
    "POSTGRES_URI"
]
for var in required_vars:
    if not os.getenv(var):
        os.environ[var] = "dummy_value"

from api.services.vector_db import vector_db_service
from api.core.config import settings

async def verify_vector_db():
    print("🧪 Starting Vector DB Verification...")
    
    if not settings.POSTGRES_URI:
        print("❌ POSTGRES_URI not set. Cannot verify.")
        return

    print(f"🔌 Connecting to: {settings.POSTGRES_URI.split('@')[1] if '@' in settings.POSTGRES_URI else 'DB'}")

    # 1. Ensure Schema
    print("\n1️⃣  Ensuring Schema...")
    try:
        vector_db_service.ensure_schema()
        print("✅ Schema ensured (table and extension)")
    except Exception as e:
        print(f"❌ Schema creation failed: {e}")
        return

    # 2. Upsert Document
    print("\n2️⃣  Testing Upsert...")
    user_id = f"test_user_{uuid.uuid4()}"
    doc_id = f"test_doc_{uuid.uuid4()}"
    chunks = ["This is a test chunk regarding systematic reviews.", "Another chunk about medical research."]
    
    # Generate random embeddings (dim 1536)
    embeddings = [
        [random.random() for _ in range(1536)],
        [random.random() for _ in range(1536)]
    ]
    
    try:
        success = vector_db_service.upsert_document_embedding(
            user_id=user_id,
            document_id=doc_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata={"source": "verification_script"}
        )
        if success:
            print(f"✅ Upsert successful for doc {doc_id}")
        else:
            print("❌ Upsert failed")
            return
    except Exception as e:
        print(f"❌ Upsert raised exception: {e}")
        return

    # 3. Search
    print("\n3️⃣  Testing Search...")
    query_vec = [random.random() for _ in range(1536)]
    
    try:
        results = vector_db_service.search_similar_documents(
            user_id=user_id,
            query_embedding=query_vec,
            limit=5
        )
        print(f"🔍 Found {len(results)} results")
        for res in results:
            print(f"   - Match: {res['content'][:30]}... (Sim: {res['similarity']:.4f})")
            
        if len(results) > 0:
            print("✅ Search returned results")
        else:
            print("❌ Search returned no results (unexpected)")
    except Exception as e:
        print(f"❌ Search raised exception: {e}")

    # 4. Delete
    print("\n4️⃣  Testing Deletion...")
    try:
        success = vector_db_service.delete_document_embeddings(user_id, doc_id)
        if success:
            print("✅ Deletion successful")
            
            # Verify deletion
            results = vector_db_service.search_similar_documents(user_id, query_vec)
            if len(results) == 0:
                print("✅ Verification: Document gone from search results")
            else:
                print(f"❌ Verification failed: Found {len(results)} results after deletion")
        else:
            print("❌ Deletion failed")
    except Exception as e:
        print(f"❌ Deletion raised exception: {e}")

    print("\n🎉 Verification Complete!")

if __name__ == "__main__":
    asyncio.run(verify_vector_db())
