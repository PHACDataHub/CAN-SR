# CAN-SR Production Deployment Guide

Complete step-by-step guide for deploying CAN-SR on Azure VM with HTTPS.

## Prerequisites

- Azure VM with Ubuntu 24.04 (T4 GPU recommended for optimal performance)
- Docker and Docker Compose installed
- Node.js and npm installed
- Python environment set up

## Step 1: Initial Setup

### 1.1 Clone and Setup Project
```bash
git clone <your-repo-url>
cd CAN-SR
```

### 1.2 Backend Setup
```bash
cd backend
pip install -r requirements.txt

# Start all services with Docker Compose
docker compose up -d

# Verify all services are running
docker compose ps
```

Expected services:
- `can-sr-api` - Main backend API
- `grobid-service` - PDF parsing
- `sr-mongodb-service` - Systematic review database
- `cit-pgdb-service` - Citations database

### 1.3 Frontend Setup
```bash
cd ../frontend
npm install
```

## Step 2: Azure Network Security Group Configuration

### 2.1 Required Inbound Port Rules

Add these rules in **Azure Portal → VM → Networking → Add inbound port rule**:

| Name | Priority | Port | Protocol | Source | Action |
|------|----------|------|----------|--------|--------|
| `Allow-Backend-8000` | 1000 | 8000 | TCP | Any | Allow |
| `Allow-Frontend-3000` | 1001 | 3000 | TCP | Any | Allow |
| `Allow-HTTP-80` | 1010 | 80 | TCP | Any | Allow |
| `Allow-HTTPS-443` | 1020 | 443 | TCP | Any | Allow |

### 2.2 Optional Service Ports (for direct access)
| Name | Priority | Port | Protocol | Source | Action |
|------|----------|------|----------|--------|--------|
| `Allow-GROBID-8070` | 1002 | 8070 | TCP | Any | Allow |
| `Allow-MongoDB-27017` | 1003 | 27017 | TCP | Any | Allow |
| `Allow-PostgreSQL-5432` | 1004 | 5432 | TCP | Any | Allow |

## Step 3: Production Build

### 3.1 Configure Frontend for External Access
```bash
cd frontend

# Create production environment file
cat > .env.local << EOF
# Frontend Environment Configuration
NEXT_PUBLIC_BACKEND_URL=http://YOUR_VM_IP:8000
NODE_ENV=development
EOF
```

### 3.2 Update Next.js Config for Production
```bash
# Edit next.config.ts to disable strict linting for production
cat > next.config.ts << EOF
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
}

export default nextConfig
EOF
```

### 3.3 Build and Deploy Frontend
```bash
# Build production version
npm run build

# Install PM2 for process management
sudo npm install -g pm2

# Start with PM2
pm2 start npm --name "can-sr-frontend" -- start

# Save PM2 configuration
pm2 save

# Setup auto-start on boot
pm2 startup
# Follow the command it provides (usually starts with 'sudo env PATH=...')
```

## Step 4: HTTPS Setup with Nginx and Let's Encrypt

### 4.1 Install Nginx
```bash
sudo apt update
sudo apt install -y nginx
```

### 4.2 Create Nginx Configuration
```bash
# Copy the CAN-SR nginx config
sudo cp deployment/can-sr.conf /etc/nginx/sites-available/can-sr.conf

# Update the server_name with your actual domain/IP
sudo nano /etc/nginx/sites-available/can-sr.conf
# Replace UPDATE_WITH_YOUR_DOMAIN with your actual domain or IP
```

### 4.3 Enable Nginx Configuration
```bash
# Enable the site
sudo ln -sf /etc/nginx/sites-available/can-sr.conf /etc/nginx/sites-enabled/

# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Start and enable Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

## Step 5: Domain Configuration

### 5.1 Configure Azure DNS Name Label
1. Go to **Azure Portal** → Your VM → **Overview**
2. Click on your **Public IP address**
3. In **DNS name label**, enter a unique name (e.g., `can-sr`)
4. Click **Save**

Your domain will be: `your-name.region.cloudapp.azure.com`

### 5.2 Update Nginx Configuration with Domain
```bash
# Update the server_name in your Nginx config
sudo sed -i 's/UPDATE_WITH_YOUR_DOMAIN/your-actual-domain.cloudapp.azure.com/g' /etc/nginx/sites-available/can-sr.conf

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

## Step 6: SSL Certificate with Let's Encrypt

### 6.1 Install Certbot
```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 6.2 Obtain SSL Certificate
```bash
# Get SSL certificate (replace with your actual domain)
sudo certbot --nginx -d your-domain.cloudapp.azure.com

# Follow the prompts:
# 1. Enter your email address
# 2. Agree to Terms of Service (Y)
# 3. Choose whether to share email with EFF (Y/N)
```

### 6.3 Verify Auto-renewal
```bash
# Test certificate renewal
sudo certbot renew --dry-run

# Check renewal timer
sudo systemctl status certbot.timer
```

## Step 7: Verification and Testing

### 7.1 Test All Endpoints
```bash
# Test HTTP (should redirect to HTTPS)
curl -I http://your-domain.cloudapp.azure.com

# Test HTTPS
curl -I https://your-domain.cloudapp.azure.com

# Test backend health
curl https://your-domain.cloudapp.azure.com/health
```

### 7.2 Check Service Status
```bash
# Check all services
docker compose ps
pm2 status
sudo systemctl status nginx
sudo systemctl status certbot.timer
```

## Final URLs

After successful deployment:

- **HTTPS (Production)**: https://your-domain.cloudapp.azure.com
- **HTTP (Redirects to HTTPS)**: http://your-domain.cloudapp.azure.com
- **API Health**: https://your-domain.cloudapp.azure.com/health
- **API Docs**: https://your-domain.cloudapp.azure.com:8000/docs

## Maintenance Commands

### Update Application
```bash
# Update frontend
cd frontend
git pull
npm run build
pm2 restart can-sr-frontend

# Update backend
cd ../backend
git pull
docker compose down
docker compose up -d
```

Or use the update scripts:
```bash
# Update frontend only
./deployment/update-frontend.sh

# Update backend only
./deployment/update-backend.sh

# Update everything
./deployment/update-all.sh
```

### Monitor Services
```bash
# Check logs
pm2 logs can-sr-frontend
docker compose logs -f

# Monitor resources
pm2 monit
docker stats
```

### SSL Certificate Management
```bash
# Check certificate status
sudo certbot certificates

# Manual renewal (if needed)
sudo certbot renew

# Check renewal logs
sudo journalctl -u certbot.timer
```

## Environment Configuration

### Backend Environment Variables (.env)

Create `/backend/.env` with:

```bash
# Azure OpenAI Settings
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=your-endpoint
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Additional model configurations
AZURE_OPENAI_GPT35_API_KEY=your-gpt35-key
AZURE_OPENAI_GPT35_ENDPOINT=your-gpt35-endpoint
AZURE_OPENAI_GPT4O_MINI_API_KEY=your-gpt4o-mini-key
AZURE_OPENAI_GPT4O_MINI_ENDPOINT=your-gpt4o-mini-endpoint

# Storage
AZURE_STORAGE_CONNECTION_STRING=your-connection-string
AZURE_STORAGE_CONTAINER_NAME=can-sr-storage

# Authentication
SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# Databases (configured in docker-compose.yml)
MONGODB_URI=mongodb://sr-mongodb-service:27017/mongodb-sr
POSTGRES_URI=postgres://admin:password@cit-pgdb-service:5432/postgres-cits

# Databricks (for database search)
DATABRICKS_INSTANCE=your-databricks-instance
DATABRICKS_TOKEN=your-databricks-token
JOB_ID_EUROPEPMC=your-europepmc-job-id
JOB_ID_PUBMED=your-pubmed-job-id
JOB_ID_SCOPUS=your-scopus-job-id

# CORS
CORS_ORIGINS=*
```

## Troubleshooting

### Common Issues

1. **Port not accessible**: Check Azure NSG rules
2. **SSL certificate failed**: Ensure domain points to correct IP
3. **Frontend not loading**: Check PM2 status and logs
4. **Backend API errors**: Check Docker container logs
5. **Nginx errors**: Check `sudo nginx -t` and `/var/log/nginx/error.log`

### Useful Commands
```bash
# Restart all services
sudo systemctl restart nginx
pm2 restart all
docker compose restart

# Check ports
sudo netstat -tlnp | grep -E ':(80|443|3000|8000)'

# Check firewall
sudo ufw status

# View Docker logs
docker compose logs -f api
docker compose logs -f grobid-service

# Check disk space
df -h

# Check memory usage
free -h
```

### Database Issues

```bash
# Reset MongoDB (WARNING: deletes all data)
docker compose stop sr-mongodb-service
sudo rm -rf backend/volumes/mongodb-sr/*
docker compose up -d sr-mongodb-service

# Reset PostgreSQL (WARNING: deletes all data)
docker compose stop cit-pgdb-service
sudo rm -rf backend/volumes/postgres-cits/*
docker compose up -d cit-pgdb-service

# Access MongoDB shell
docker exec -it sr-mongodb-service mongosh

# Access PostgreSQL shell
docker exec -it cit-pgdb-service psql -U admin -d postgres-cits
```

## Success!

Your CAN-SR platform is now deployed with:
- ✅ Production-optimized build
- ✅ HTTPS security with auto-renewal
- ✅ Professional domain name
- ✅ Reverse proxy with Nginx
- ✅ Process management with PM2
- ✅ Auto-restart on server reboot
- ✅ 4 Docker services (API, GROBID, MongoDB, PostgreSQL)

**Access your application at**: https://your-domain.cloudapp.azure.com

## Monitoring and Maintenance

### Regular Maintenance Tasks

1. **Weekly**: Check certificate renewal status
2. **Monthly**: Update system packages and Docker images
3. **As needed**: Review logs for errors
4. **Before updates**: Backup databases

### Backup Strategy

```bash
# Backup MongoDB
docker exec sr-mongodb-service mongodump --out=/data/backup

# Backup PostgreSQL
docker exec cit-pgdb-service pg_dump -U admin postgres-cits > backup.sql

# Backup uploads folder
tar -czf uploads-backup.tar.gz backend/uploads/
```

## Updating Your Deployment

After initial deployment, use the scripts in the `deployment/` directory to update your application:

```bash
# Update frontend only
./deployment/update-frontend.sh

# Update backend only
./deployment/update-backend.sh

# Update everything
./deployment/update-all.sh
```

## Additional Resources

- API Documentation: https://your-domain.cloudapp.azure.com:8000/docs
- GitHub Repository: [Link to your repo]
- Support: [Contact information]
