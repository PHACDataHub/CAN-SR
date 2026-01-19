# CAN-SR (Canadian Systematic Review Platform)

AI-powered systematic review platform for the Government of Canada, built with Next.js frontend and Python FastAPI backend with AI-enabled automation for screening and data extraction.

## Quick Start

### Production Deployment (Recommended)

For full production deployment with HTTPS on Azure VM:

```bash
# 1. Deploy backend services
cd backend
docker compose up -d

# 2. Deploy frontend (production build)
cd ../frontend
npm install
npm run build
pm2 start npm --name "can-sr-frontend" -- start
```

**Complete deployment guide**: See `DEPLOY.md` for full Azure VM setup with HTTPS.

### Development Setup

#### Backend Development
```bash
cd backend

# Start all services with Docker Compose
docker compose up -d

# Or run API directly for development
pip install -r requirements.txt
uvicorn main:app --reload
```

#### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

## Architecture

- **Frontend**: Next.js 15 with React 19, TypeScript, Tailwind CSS
- **Backend**: FastAPI with Python, async/await patterns
- **Databases**: 
  - MongoDB - Systematic review metadata
  - PostgreSQL - Citation storage and screening data
- **Document Processing**: GROBID for PDF parsing and full-text extraction
- **AI Services**: Azure OpenAI (GPT-4o, GPT-3.5-turbo, GPT-4o-mini) for screening and extraction
- **Storage**: Azure Blob Storage for file uploads
- **Authentication**: JWT-based auth system

## Core Features

### Systematic Review Workflow
1. **Review Setup** - Create and configure systematic review projects
2. **Citation Upload** - Import citations from databases (PubMed, Scopus, Europe PMC)
3. **L1 Screening** - AI-assisted title/abstract screening
4. **L2 Screening** - AI-assisted full-text screening
5. **Data Extraction** - Automated parameter extraction from included studies
6. **Database Search** - Integrated search across scientific databases

### AI Capabilities
- **Intelligent Screening**: AI agents help screen citations based on inclusion/exclusion criteria
- **Parameter Extraction**: Automatically extract study parameters from full-text articles
- **Human Validation**: All AI decisions can be reviewed and validated by researchers

## Updating Deployment

After making code changes to your live deployment:

```bash
# Update frontend only
./deployment/update-frontend.sh

# Update backend only
./deployment/update-backend.sh

# Update everything
./deployment/update-all.sh
```

## Docker Services

When running with Docker Compose, the following services are available:

- **can-sr-api** (port 8000) - Main backend API
- **grobid-service** (port 8070) - PDF parsing and text extraction
- **sr-mongodb-service** (port 27017) - Systematic review database
- **cit-pgdb-service** (port 5432) - Citations database

## Service URLs (Development)

When running locally:

- **Main API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Frontend**: http://localhost:3000
- **GROBID Service**: http://localhost:8070

## Documentation

- **`DEPLOY.md`** - Complete Azure VM deployment guide with HTTPS
- **`deployment/`** - Update scripts and deployment utilities
- **`deployment/can-sr.conf`** - Nginx configuration for production

## Code Formatting

This project uses [Prettier](https://prettier.io/) for consistent code style:

```bash
cd frontend
npm run format
```

## Project Structure

```
CAN-SR/
├── backend/              # FastAPI Python backend
│   ├── api/             # API routes and services
│   │   ├── auth/        # Authentication
│   │   ├── files/       # File upload management
│   │   ├── sr/          # Systematic review setup
│   │   ├── citations/   # Citation management
│   │   ├── screen/      # Screening AI agents
│   │   ├── extract/     # Extraction AI agents
│   │   └── database_search/ # Database search integration
│   ├── docker-compose.yml
│   └── Dockerfile
├── frontend/            # Next.js React frontend
│   ├── app/            # App router pages
│   │   ├── can-sr/     # CAN-SR main interface
│   │   └── api/        # API routes (Next.js middleware)
│   └── components/     # UI components
├── deployment/          # Deployment scripts and configs
│   ├── can-sr.conf     # Nginx configuration
│   ├── update-frontend.sh
│   ├── update-backend.sh
│   └── update-all.sh
└── DEPLOY.md           # Production deployment guide
```

## Environment Variables

### Backend (.env)
```bash
# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=your-endpoint
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Storage
AZURE_STORAGE_CONNECTION_STRING=your-connection-string

# Databases
MONGODB_URI=mongodb://localhost:27017/mongodb-sr
POSTGRES_URI=postgres://admin:password@localhost:5432/postgres-cits

# Databricks (for database search)
DATABRICKS_INSTANCE=your-instance
DATABRICKS_TOKEN=your-token
```

### Frontend (.env.local)
```bash
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Troubleshooting

### Backend Issues
```bash
# Check service status
cd backend
docker compose ps

# View logs
docker compose logs -f api

# Restart services
docker compose restart

# Rebuild containers
docker compose down
docker compose build
docker compose up -d
```

### Frontend Issues
```bash
# Check PM2 status
pm2 status

# View logs
pm2 logs can-sr-frontend

# Restart
pm2 restart can-sr-frontend
```

### Database Issues
```bash
# MongoDB
docker compose logs sr-mongodb-service

# PostgreSQL
docker compose logs cit-pgdb-service

# Reset databases (WARNING: deletes all data)
docker compose down -v
docker compose up -d
```

## Future Enhancements

### Planned AI Agents
- **Literature Review Agent**: Automated literature synthesis and summary generation
- **Quality Assessment Agent**: Automated risk of bias and quality assessment
- **Meta-Analysis Agent**: Statistical analysis and forest plot generation
- **Citation Network Agent**: Analyze citation networks and identify key papers
- **Duplicate Detection Agent**: Intelligent duplicate citation detection

See `AGENTS_ROADMAP.md` for detailed implementation plans.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test locally with Docker Compose
4. Format code with `npm run format`
5. Submit a pull request

## License

See LICENSE file for details.

## Support

For issues and questions:
- Check `DEPLOY.md` for deployment help
- Review API documentation at `/docs` endpoint
- Contact the development team
