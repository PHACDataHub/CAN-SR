#!/bin/bash

# CAN-SR - Production Deployment Script
# Deploys the systematic review platform with essential services
# Note: CAN-SR uses Azure OpenAI for AI features (no local GPU required)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
BUILD=false
UPDATE_DEPS=false
RESET_DB=false
DROP_ALL=false
DEV=false

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
        --reset-db)
            RESET_DB=true
            shift
            ;;
        --drop-all-dbs)
            DROP_ALL=true
            shift
            ;;
        --dev)
            DEV=true
            shift
            ;;
        -h|--help)
            echo "CAN-SR - Production Deployment"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build         Rebuild Docker images"
            echo "  --update-deps   Update Python dependencies"
            echo "  --reset-db      Reset databases (WARNING: deletes all data)"
            echo "  --drop-all-dbs  Drop ALL DB data on disk (stronger than --reset-db; wipes Postgres volume dir)"
            echo "  --dev           Development mode with hot reload"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Start with existing images"
            echo "  $0 --build           # Rebuild and start"
            echo "  $0 --reset-db        # Reset databases and start fresh"
            echo "  $0 --dev             # Development mode"
            exit 0
            ;;
        *)
            echo "Unknown option $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🏛️  CAN-SR - Systematic Review Platform${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}💡 Uses Azure OpenAI for AI features (CPU-only)${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker first.${NC}"
    exit 1
fi


# Reset databases if requested
if [ "$RESET_DB" = true ]; then
    echo -e "${YELLOW}🗑️  Resetting databases...${NC}"
    docker compose down -v
    # NOTE: docker-compose mounts ./volumes/postgres (see backend/docker-compose.yml)
    # Keep legacy path cleanup as best-effort.
    sudo rm -rf volumes/postgres 2>/dev/null || true
    sudo rm -rf volumes/postgres-cits 2>/dev/null || true
    echo -e "${GREEN}✅ Databases reset${NC}"
fi

# Drop ALL database data on disk if requested (intended for validation resets)
if [ "$DROP_ALL" = true ]; then
    echo -e "${YELLOW}🧨 Dropping ALL database data (full wipe)...${NC}"
    docker compose down -v
    # Wipe compose-mounted postgres directory
    sudo rm -rf volumes/postgres 2>/dev/null || true
    # Legacy dirs (best-effort)
    sudo rm -rf volumes/postgres-cits 2>/dev/null || true
    echo -e "${GREEN}✅ All DB data wiped${NC}"
fi

# Build images if requested
if [ "$BUILD" = true ]; then
    echo -e "${BLUE}🔨 Building Docker images...${NC}"
    docker compose build --no-cache
    echo -e "${GREEN}✅ Images built successfully${NC}"
fi

# Create necessary directories
echo -e "${BLUE}📁 Creating volume directories...${NC}"
mkdir -p volumes/{postgres}
# Legacy dir (safe to keep if present)
mkdir -p volumes/{postgres-cits}
mkdir -p uploads/users

echo -e "${GREEN}🚀 Starting services...${NC}"

# Start services
echo -e "${BLUE}🏗️  Starting CAN-SR services...${NC}"

# Start database services first
echo -e "${BLUE}🗄️  Starting databases...${NC}"
docker compose up -d pgdb-service --remove-orphans
sleep 10

# Start GROBID service
echo -e "${BLUE}📄 Starting GROBID (PDF parsing)...${NC}"
docker compose up -d grobid-service --remove-orphans
sleep 10

# Start main API
echo -e "${BLUE}🌐 Starting main API...${NC}"
if [ "$DEV" = true ]; then
    docker compose up -d api --remove-orphans
else
    docker compose up -d api --remove-orphans
fi

# Wait for services to be healthy
echo -e "${BLUE}� Checking service health...${NC}"
sleep 15

# Check service status
echo -e "${BLUE}📊 Service Status:${NC}"
services=("can-sr-api" "grobid-service" "pgdb-service")

for service in "${services[@]}"; do
    if docker ps --format "table {{.Names}}" | grep -q "$service"; then
        echo -e "${GREEN}✅ $service: Running${NC}"
    else
        echo -e "${RED}❌ $service: Not running${NC}"
    fi
done

echo ""
echo -e "${GREEN}� Deployment complete!${NC}"
echo ""
echo -e "${BLUE}� Service URLs:${NC}"
echo -e "  🌐 Main API:              http://localhost:8000"
echo -e "  📚 API Documentation:     http://localhost:8000/docs"
echo -e "  🏥 Health Check:          http://localhost:8000/health"
echo -e "  📄 GROBID Service:        http://localhost:8070"
echo -e "  🗄️  PostgreSQL:            localhost:5432"
echo ""
echo -e "${BLUE}🔬 CAN-SR Features:${NC}"
echo -e "  ✅ Systematic review management"
echo -e "  ✅ AI-powered screening (L1 & L2)"
echo -e "  ✅ Automated data extraction"
echo -e "  ✅ Database search integration"
echo -e "  ✅ Citation management"
echo ""
echo -e "${YELLOW}� Next Steps:${NC}"
echo -e "  1. Test the API: curl http://localhost:8000/health"
echo -e "  2. Access API docs: http://localhost:8000/docs"
echo -e "  3. Start the frontend (see README.md)"
echo -e "  4. Monitor logs: docker compose logs -f api"
echo ""

if [ "$DEV" = false ]; then
    echo -e "${BLUE}� To view logs: docker compose logs -f${NC}"
    echo -e "${BLUE}🛑 To stop: docker compose down${NC}"
    echo -e "${BLUE}� To restart: docker compose restart${NC}"
fi
