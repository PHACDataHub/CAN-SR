# CAN-SR Backend

FastAPI backend for the Canadian Systematic Review (CAN-SR) Platform - an AI-powered systematic review platform for the Government of Canada.

## Overview

CAN-SR Backend provides a production-ready REST API for managing systematic reviews with AI-assisted screening and data extraction capabilities.

### **Key Features**
- **Systematic Review Management** - Create and manage review projects
- **Citation Processing** - Import and manage citations from multiple databases
- **AI-Powered Screening** - Automated L1 (title/abstract) and L2 (full-text) screening
- **Data Extraction** - AI-assisted parameter extraction from studies
- **Database Integration** - Search across PubMed, Scopus, Europe PMC
- **PDF Processing** - Full-text extraction using GROBID
- **Azure OpenAI Integration** - GPT-4o, GPT-4o-mini, GPT-3.5-turbo for AI features
- **JWT Authentication** - Secure user authentication
- **Storage** - Local filesystem or Azure Blob Storage (connection string or Entra)

## Architecture

### **Tech Stack**
- **API Framework**: FastAPI with Python
- **Databases**: 
  - MongoDB (port 27017) - Systematic review metadata
  - PostgreSQL (port 5432) - Citation storage and screening data
- **Document Processing**: GROBID (port 8070) - PDF parsing and full-text extraction
- **AI Services**: Azure OpenAI (cloud-based, no GPU required)
- **Storage**: Azure Blob Storage
- **Authentication**: JWT-based auth

### **Design Philosophy**
- **CPU-Only Deployment**: No GPU requirements - all AI via Azure OpenAI
- **Microservices**: Containerized services via Docker Compose
- **Async Processing**: FastAPI async/await patterns for performance
- **Production Ready**: Health checks, logging, error handling

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Azure OpenAI Service account
- Azure Blob Storage account
- Python 3.11+ (for local development)

### 1. Configure Environment
Create `.env` file in the `backend/` directory:
```bash
# Azure OpenAI (Required)
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Storage
# STORAGE_MODE is strict: local | azure | entra
STORAGE_MODE=local

# Storage container name
# - local: folder name under LOCAL_STORAGE_BASE_PATH
# - azure/entra: blob container name
STORAGE_CONTAINER_NAME=can-sr-storage

# local storage
LOCAL_STORAGE_BASE_PATH=uploads

# azure storage (account name + key)
# STORAGE_MODE=azure
AZURE_STORAGE_ACCOUNT_NAME=youraccount
AZURE_STORAGE_ACCOUNT_KEY=your-key

# entra storage (Managed Identity / DefaultAzureCredential)
# STORAGE_MODE=entra
AZURE_STORAGE_ACCOUNT_NAME=youraccount

# Databases (Docker defaults - change for production)


# Postgres configuration
POSTGRES_MODE=docker  # docker | local | azure

# Canonical Postgres connection settings (single set)
# - docker/local: POSTGRES_PASSWORD is required
# - azure: POSTGRES_PASSWORD is ignored (Entra token auth via DefaultAzureCredential)
POSTGRES_HOST=pgdb-service
POSTGRES_DATABASE=postgres
POSTGRES_USER=admin
POSTGRES_PASSWORD=password

# Local Postgres (developer machine)
# POSTGRES_MODE=local
# POSTGRES_HOST=localhost
# POSTGRES_DATABASE=grep
# POSTGRES_USER=postgres
# POSTGRES_PASSWORD=123

# Azure Database for PostgreSQL (Entra auth)
# POSTGRES_MODE=azure
# POSTGRES_HOST=<your-azure-postgres-hostname>
# POSTGRES_DATABASE=<db>
# POSTGRES_USER=<your-entra-upn>
# POSTGRES_PASSWORD=  # not used in azure mode

# GROBID Service
GROBID_SERVICE_URL=http://grobid-service:8070

# Databricks (for database search - optional)
DATABRICKS_INSTANCE=your-instance
DATABRICKS_TOKEN=your-token

# Security
SECRET_KEY=your-very-secure-secret-key-here
```

### 2. Deploy with Docker Compose
```bash
# Quick start (uses existing images)
./deploy.sh

# Build from scratch
./deploy.sh --build

# Development mode
./deploy.sh --dev

# Reset databases (WARNING: deletes all data)
./deploy.sh --reset-db
```

### 3. Verify Deployment
```bash
# Check API health
curl http://localhost:8000/health

# Check GROBID service
curl http://localhost:8070/api/isalive

# Check service status
docker compose ps
```

## Service Endpoints

When running with Docker Compose:

- **Main API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **GROBID Service**: http://localhost:8070
- **MongoDB**: localhost:27017
- **PostgreSQL**: localhost:5432

## Docker Services

The system includes these containerized services:

### **Core Services**
- **can-sr-api** (port 8000) - Main FastAPI application
- **grobid-service** (port 8070) - PDF parsing and full-text extraction
- **sr-mongodb-service** (port 27017) - Systematic review database
- **cit-pgdb-service** (port 5432) - Citations database

## API Structure

```
backend/
├── api/
│   ├── auth/              # Authentication & user management
│   ├── sr/                # Systematic review CRUD operations
│   ├── citations/         # Citation import and management
│   ├── screen/            # L1/L2 screening AI agents
│   ├── extract/           # Data extraction AI agents
│   ├── database_search/   # PubMed, Scopus, Europe PMC integration
│   ├── files/             # File upload and Azure Blob integration
│   ├── core/              # Configuration and utilities
│   └── router.py          # Main API router
├── main.py                # FastAPI application entry point
├── docker-compose.yml     # Service orchestration
├── Dockerfile             # API container definition
├── deploy.sh              # Deployment script
└── requirements.txt       # Python dependencies
```

## Development

### Local Development (without Docker)
```bash
# Install dependencies
pip install -r requirements.txt

# Start external services via Docker
docker compose up -d grobid-service sr-mongodb-service cit-pgdb-service

# Run API locally with hot reload
uvicorn main:app --reload --port 8000
```

### Running Tests
```bash
# Run tests (when test suite is implemented)
pytest

# With coverage
pytest --cov=api
```

## Deployment Options

### Using the Deploy Script

The `deploy.sh` script provides several options:

```bash
# Standard deployment
./deploy.sh

# Rebuild all images
./deploy.sh --build

# Update Python dependencies
./deploy.sh --update-deps

# Reset all databases (deletes data!)
./deploy.sh --reset-db

# Development mode with auto-reload
./deploy.sh --dev

# Combination
./deploy.sh --build --reset-db
```

### Manual Docker Compose

```bash
# Start all services
docker compose up -d

# Start specific service
docker compose up -d api

# Stop all services
docker compose down

# View logs
docker compose logs -f api
docker compose logs -f grobid-service

# Restart service
docker compose restart api
```

## Environment Variables Reference

### Required Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | `abc123...` |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | `https://your-resource.openai.azure.com` |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Model deployment name | `gpt-4o` |
| `STORAGE_MODE` | Storage backend selector | `local` |
| `LOCAL_STORAGE_BASE_PATH` | Local storage base path (when local) | `uploads` |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob (when STORAGE_MODE=azure) | `DefaultEndpointsProtocol=https;...` |
| `ENTRA_AZURE_STORAGE_ACCOUNT_NAME` | Azure account (when STORAGE_MODE=entra) | `mystorageacct` |
| `SECRET_KEY` | JWT token signing key | `your-secure-secret-key` |

### Optional Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URI` | MongoDB connection string | `mongodb://sr-mongodb-service:27017/mongodb-sr` |
| `POSTGRES_MODE` | Postgres connection mode: `docker` \| `local` \| `azure` | `docker` |
| `POSTGRES_HOST` | Postgres host (docker: service name; local: localhost; azure: FQDN) | `pgdb-service` |
| `POSTGRES_DATABASE` | Postgres database name | `postgres` |
| `POSTGRES_USER` | Postgres user (azure: Entra UPN or role) | `admin` |
| `POSTGRES_PASSWORD` | Postgres password (ignored when POSTGRES_MODE=azure) | `password` |
| `GROBID_SERVICE_URL` | GROBID service URL | `http://grobid-service:8070` |
| `DATABRICKS_INSTANCE` | Databricks workspace URL | - |
| `DATABRICKS_TOKEN` | Databricks access token | - |

## AI Features

### Azure OpenAI Models
CAN-SR uses Azure OpenAI for all AI capabilities:

- **GPT-4o**: High-quality screening and extraction
- **GPT-4o-mini**: Fast, cost-effective screening
- **GPT-3.5-turbo**: Quick processing for simple tasks

### AI Agents
- **L1 Screening Agent**: Title/abstract screening
- **L2 Screening Agent**: Full-text screening
- **Extraction Agent**: Parameter extraction from studies
- **Database Search Agent**: Query optimization for scientific databases

## Troubleshooting

### Common Issues

#### **Services won't start**
```bash
# Check Docker is running
docker info

# Check for port conflicts
sudo lsof -i :8000  # API port
sudo lsof -i :8070  # GROBID port
sudo lsof -i :27017 # MongoDB port
sudo lsof -i :5432  # PostgreSQL port

# View service logs
docker compose logs -f
```

#### **Azure connection errors**
```bash
# Verify .env file exists and has correct values
cat .env | grep AZURE

# Test Azure OpenAI connection
curl -X POST "${AZURE_OPENAI_ENDPOINT}/openai/deployments/${AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version=2024-02-15-preview" \
  -H "api-key: ${AZURE_OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}],"max_tokens":10}'
```

#### **Database connection issues**
```bash
# Check MongoDB is running
docker compose logs sr-mongodb-service

# Check PostgreSQL is running
docker compose logs cit-pgdb-service

# Reset databases (WARNING: deletes all data)
./deploy.sh --reset-db
```

#### **GROBID service issues**
```bash
# Check GROBID health
curl http://localhost:8070/api/isalive

# Restart GROBID
docker compose restart grobid-service

# View GROBID logs
docker compose logs -f grobid-service
```

### Useful Commands

```bash
# View all container logs
docker compose logs -f

# Check service health
docker compose ps

# Restart all services
docker compose restart

# Rebuild and restart a specific service
docker compose up -d --build api

# Clean everything (including volumes)
docker compose down -v
sudo rm -rf volumes/

# Monitor resource usage
docker stats
```

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# GROBID health
curl http://localhost:8070/api/isalive

# MongoDB connection
mongosh mongodb://localhost:27017/mongodb-sr

# PostgreSQL connection
psql postgres://admin:password@localhost:5432/postgres-cits
```

## Production Deployment

For production deployment on Azure VM with HTTPS:
1. See the main `DEPLOY.md` in the repository root
2. Use the deployment scripts in `../deployment/`
3. Configure Nginx reverse proxy (see `../deployment/can-sr.conf`)

### Update Scripts
```bash
# Update backend in production
cd ../deployment
./update-backend.sh

# Update all services
./update-all.sh
```

## API Documentation

When the API is running, interactive documentation is available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Contributing

1. Follow the project structure in `api/`
2. Add new routes to `api/router.py`
3. Use async/await patterns for database and external API calls
4. Add proper error handling and logging
5. Update this README when adding new services or features

## Support

For deployment help and troubleshooting:
- Review `../DEPLOY.md` for production deployment
- Check API documentation at `/docs` endpoint
- Review logs with `docker compose logs -f`
- See `../AGENTS_ROADMAP.md` for planned AI features

## License

See LICENSE file in repository root for details.
