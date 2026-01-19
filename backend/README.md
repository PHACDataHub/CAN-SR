# Government of Canada Science GPT Backend

A production-ready FastAPI backend with **dual MilvusDB architecture** for the Government of Canada Science GPT application.

## Architecture Overview

### **Dual MilvusDB Design**
- **Base Knowledge DB**: Shared government documents (port 19530)
- **User Knowledge DB**: User-specific documents (port 19531)
- **Microservices**: BGE-M3 embeddings, reranker, Milvus services
- **GPU Acceleration**: NVIDIA T4 support with CUDA 12.8

### **Key Features**
- **Azure OpenAI Integration** - Multiple models (gpt-4o, gpt-4o-mini, gpt-3.5-turbo, gpt-4.1-mini)
- **Hybrid Search** - Dense + sparse vectors with configurable weights
- **Advanced Chunking** - Docling-based with hierarchical/hybrid methods
- **JWT Authentication** - Secure user authentication
- **Azure Blob Storage** - Scalable document storage
- **Production Ready** - Docker containerized deployment

## Quick Start

### Prerequisites
- Docker & Docker Compose
- NVIDIA GPU with CUDA support
- Azure OpenAI Service account
- Azure Blob Storage account

### 1. Configure Environment
Create `.env` file:
```bash
# Azure OpenAI (Required)
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Azure Storage (Required)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=your-account;AccountKey=your-key;EndpointSuffix=core.windows.net

# Security (Required)
SECRET_KEY=your-very-secure-secret-key-here
```

### 2. Deploy with Docker
```bash
# Build and start all services
./deploy.sh

# Or with specific options
./deploy.sh --build --reset_milvus
```

## Service Endpoints

- **API Server**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **BGE-M3 Embeddings**: http://localhost:8001
- **Reranker Service**: http://localhost:8002
- **Base Milvus Service**: http://localhost:8003
- **User Milvus Service**: http://localhost:8004

## Test Your Setup

```bash
# Test API health
curl http://localhost:8000/health

# Test embeddings service
curl http://localhost:8001/health

# Test reranker service
curl http://localhost:8002/health
```

## Administration Scripts

```bash
# Initialize/add base knowledge documents
python manual_init_base.py
```

## Docker Services

The system includes these containerized services:

**Core Services:**
- **API Container** (8000) - Main FastAPI application
- **BGE-M3 Service** (8001) - GPU-accelerated embeddings
- **Reranker Service** (8002) - GPU-accelerated reranking

**Dual MilvusDB Architecture:**
- **Base Milvus** (19530) - Shared government knowledge
- **User Milvus** (19531) - User-specific documents
- **Base Milvus Service** (8003) - Base knowledge API
- **User Milvus Service** (8004) - User knowledge API

**Storage:**
- **MinIO Base** (9000/9001) - Base knowledge storage
- **MinIO User** (9002/9003) - User knowledge storage

## Important Notes

1. **GPU Requirements**: NVIDIA T4 with CUDA 12.8 support
2. **Environment Variables**: Configure `.env` file with Azure credentials
3. **Base Knowledge**: Initialize once with `python manual_init_base.py`
4. **Docker Deployment**: Use `./deploy.sh` for production deployment

## Troubleshooting

**Common Issues:**
- **GPU not detected**: Ensure NVIDIA Docker runtime is installed
- **Azure connection**: Verify your `.env` file has correct credentials
- **Port conflicts**: Check if ports 8000-8004, 19530-19531 are available
- **Memory issues**: Ensure sufficient GPU memory for BGE-M3 and reranker

**Deployment Commands:**
```bash
# Full rebuild with reset
./deploy.sh --build --reset_milvus

# Development mode
./deploy.sh --dev

# Update dependencies
./deploy.sh --update_deps

# CPU-only mode (no GPU)
./deploy.sh --no_gpu
```

**Get Help:**
```bash
# Check all service health
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# View logs
docker-compose logs -f api
docker-compose logs -f bgem3-service
docker-compose logs -f reranker-service
docker-compose logs -f grobid-service
```
