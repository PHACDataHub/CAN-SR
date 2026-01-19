#!/bin/bash

# Government of Canada Science GPT - Production Deployment Script
# Deploys the system with dual MilvusDB architecture for optimal performance and scalability

set -e

# Environment Setup Function
setup_environment() {
    echo -e "${BLUE}🔧 Setting up environment for NVIDIA T4 GPU...${NC}"

    # Set environment variables for current session
    export TORCH_CUDA_ARCH_LIST="7.5"
    export TRANSFORMERS_VERBOSITY=error
    export TOKENIZERS_PARALLELISM=false

    # Add to conda environment if sciencegpt exists
    if command -v conda >/dev/null 2>&1 && conda env list | grep -q "sciencegpt"; then
        echo -e "${BLUE}📦 Configuring conda environment 'sciencegpt'...${NC}"
        conda env config vars set TORCH_CUDA_ARCH_LIST="7.5" -n sciencegpt 2>/dev/null || true
        conda env config vars set TRANSFORMERS_VERBOSITY=error -n sciencegpt 2>/dev/null || true
        conda env config vars set TOKENIZERS_PARALLELISM=false -n sciencegpt 2>/dev/null || true
        echo -e "${GREEN}✅ Conda environment configured${NC}"
    fi

    # Add to shell profile if not already present
    if [ ! -f ~/.bashrc ] || ! grep -q "TORCH_CUDA_ARCH_LIST" ~/.bashrc; then
        echo -e "${BLUE}🔧 Adding permanent environment variables to ~/.bashrc...${NC}"
        echo "" >> ~/.bashrc
        echo "# NVIDIA T4 GPU optimization for Government Science GPT" >> ~/.bashrc
        echo 'export TORCH_CUDA_ARCH_LIST="7.5"' >> ~/.bashrc
        echo 'export TRANSFORMERS_VERBOSITY=error' >> ~/.bashrc
        echo 'export TOKENIZERS_PARALLELISM=false' >> ~/.bashrc
        echo -e "${GREEN}✅ Environment variables added to ~/.bashrc${NC}"
    fi

    echo -e "${GREEN}✅ Environment setup complete${NC}"
}

# Set CUDA architecture for NVIDIA T4 GPU (compute capability 7.5)
export TORCH_CUDA_ARCH_LIST="7.5"
export TRANSFORMERS_VERBOSITY=error
export TOKENIZERS_PARALLELISM=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
BUILD=false
UPDATE_DEPS=false
RESET_MILVUS=false
GPU=true
DEV=false
SETUP_ENV=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD=true
            shift
            ;;
        --update-deps)
            UPDATE_DEPS=true
            shift
            ;;
        --reset-milvus)
            RESET_MILVUS=true
            shift
            ;;
        --no-gpu)
            GPU=false
            shift
            ;;
        --dev)
            DEV=true
            shift
            ;;
        --setup-env)
            SETUP_ENV=true
            shift
            ;;
        -h|--help)
            echo "Government of Canada Science GPT - Production Deployment"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build         Rebuild Docker images"
            echo "  --update-deps   Update Python dependencies"
            echo "  --reset-milvus  Reset Milvus databases (WARNING: deletes all data)"
            echo "  --no-gpu        Use CPU-only mode"
            echo "  --dev           Development mode with hot reload"
            echo "  --setup-env     Setup permanent environment variables for T4 GPU"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Start with existing images"
            echo "  $0 --build           # Rebuild and start"
            echo "  $0 --reset-milvus    # Reset databases and start fresh"
            echo "  $0 --no-gpu          # Use CPU-only mode"
            exit 0
            ;;
        *)
            echo "Unknown option $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🏛️  Government of Canada Science GPT - Dual MilvusDB Architecture${NC}"
echo -e "${BLUE}================================================================${NC}"

# Setup environment if requested
if [ "$SETUP_ENV" = true ]; then
    setup_environment
    echo ""
    echo -e "${GREEN}🎯 Environment setup complete!${NC}"
    echo -e "${YELLOW}📝 To activate immediately:${NC}"
    echo -e "   source ~/.bashrc"
    echo -e "   conda deactivate && conda activate sciencegpt"
    echo ""
    exit 0
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Check for NVIDIA Docker runtime if GPU is enabled
if [ "$GPU" = true ]; then
    if ! docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  GPU support not available. Falling back to CPU mode.${NC}"
        GPU=false
    else
        echo -e "${GREEN}✅ GPU support detected${NC}"
    fi
fi

# Reset Milvus databases if requested
if [ "$RESET_MILVUS" = true ]; then
    echo -e "${YELLOW}🗑️  Resetting Milvus databases...${NC}"
    docker compose down -v
    sudo rm -rf volumes/milvus-base volumes/milvus-user volumes/etcd-base volumes/etcd-user volumes/minio-base volumes/minio-user 2>/dev/null || true
    echo -e "${GREEN}✅ Milvus databases reset${NC}"
fi

# Build images if requested
if [ "$BUILD" = true ]; then
    echo -e "${BLUE}🔨 Building Docker images...${NC}"
    docker compose build --no-cache
    echo -e "${GREEN}✅ Images built successfully${NC}"
fi

# Create necessary directories
echo -e "${BLUE}📁 Creating volume directories...${NC}"
mkdir -p volumes/{milvus-base,milvus-user,etcd-base,etcd-user,minio-base,minio-user}

# Set GPU profile
if [ "$GPU" = true ]; then
    export COMPOSE_PROFILES="gpu"
    echo -e "${GREEN}🚀 Starting services with GPU acceleration...${NC}"
else
    export COMPOSE_PROFILES="cpu"
    echo -e "${YELLOW}🚀 Starting services in CPU mode...${NC}"
fi

# Start services in the correct order
echo -e "${BLUE}🏗️  Starting dual MilvusDB architecture...${NC}"

# Start base knowledge infrastructure
echo -e "${BLUE}📊 Starting base knowledge database...${NC}"
docker compose up -d milvus-base-etcd milvus-base-minio
sleep 5
docker compose up -d milvus-base-standalone
sleep 10

# Start user knowledge infrastructure  
echo -e "${BLUE}👥 Starting user knowledge database...${NC}"
docker compose up -d milvus-user-etcd milvus-user-minio
sleep 5
docker compose up -d milvus-user-standalone
sleep 10

# Start Milvus services
echo -e "${BLUE}🔧 Starting Milvus services...${NC}"
docker compose up -d milvus-base-service milvus-user-service
sleep 5

# Start Database services
echo -e "${BLUE}🔧 Starting Database services...${NC}"
docker compose up -d sr-mongodb-service cit-pgdb-service
sleep 5

# Start AI services
echo -e "${BLUE}🤖 Starting AI services...${NC}"
if [ "$GPU" = true ]; then
    # docker build --no-cache grobid-service
    docker compose up -d bgem3-service reranker-service grobid-service
else
    echo -e "${YELLOW}⚠️  CPU-only mode not implemented. Using GPU services.${NC}"
    docker compose up -d bgem3-service reranker-service grobid-service
fi
sleep 10

# Start main API
echo -e "${BLUE}🌐 Starting main API...${NC}"
# if [ "$BUILD" = true ]; then
#     docker compose build --no-cache api
# fi

if [ "$DEV" = true ]; then
    docker compose up -d api
else
    docker compose up -d api
fi

# Wait for services to be healthy
echo -e "${BLUE}🏥 Checking service health...${NC}"
sleep 15

# Check service status
echo -e "${BLUE}📊 Service Status:${NC}"
services=("milvus-base-standalone" "milvus-user-standalone" "milvus-base-service" "milvus-user-service" "bgem3-service" "reranker-service" "grobid-service" "sr-mongodb-service" "cit-pgdb-service" "government-sciencegpt-api")

for service in "${services[@]}"; do
    if docker ps --format "table {{.Names}}" | grep -q "$service"; then
        echo -e "${GREEN}✅ $service: Running${NC}"
    else
        echo -e "${RED}❌ $service: Not running${NC}"
    fi
done

echo ""
echo -e "${GREEN}🎉 Deployment complete!${NC}"
echo ""
echo -e "${BLUE}📋 Service URLs:${NC}"
echo -e "  🌐 Main API:              http://localhost:8000"
echo -e "  🧠 BGE-M3 Embeddings:    http://localhost:8001"
echo -e "  🔄 Reranker:              http://localhost:8002"
echo -e "  📊 Base Milvus Service:   http://localhost:8003"
echo -e "  👥 User Milvus Service:   http://localhost:8004"
echo -e "  🗄️  Base Milvus DB:        http://localhost:19530"
echo -e "  🗄️  User Milvus DB:        http://localhost:19531"
echo -e "  📁 Base MinIO:            http://localhost:9000"
echo -e "  📁 User MinIO:            http://localhost:9002"
echo ""
echo -e "${BLUE}🏛️  Architecture Benefits:${NC}"
echo -e "  ✅ Improved scalability and concurrency"
echo -e "  ✅ Better isolation between base and user knowledge"
echo -e "  ✅ Independent scaling of knowledge bases"
echo -e "  ✅ Enhanced security and fault tolerance"
echo ""
echo -e "${YELLOW}📝 Next Steps:${NC}"
echo -e "  1. Test the API: curl http://localhost:8000/health"
echo -e "  2. Upload documents via the frontend"
echo -e "  3. Monitor logs: docker compose logs -f api"
echo ""

if [ "$DEV" = false ]; then
    echo -e "${BLUE}🔍 To view logs: docker compose logs -f${NC}"
    echo -e "${BLUE}🛑 To stop: docker compose down${NC}"
fi
