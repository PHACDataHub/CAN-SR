# 🚀 Deployment Directory

This directory contains all deployment-related files and scripts for Science-GPT-v2.

## 📁 Directory Contents

### 📜 Scripts
- **`update-frontend.sh`** - Updates frontend code and restarts PM2
- **`update-backend.sh`** - Updates backend code and restarts Docker containers  
- **`update-all.sh`** - Updates both frontend and backend

### 📋 Documentation
- **`UPDATE_DEPLOYMENT.md`** - Detailed guide for updating deployments
- **`README.md`** - This file

### ⚙️ Configuration
- **`science-gpt.conf`** - Nginx configuration file for reverse proxy

## 🎯 Quick Usage

### Update Frontend Only
```bash
./deployment/update-frontend.sh
```

### Update Backend Only
```bash
./deployment/update-backend.sh
```

### Update Everything
```bash
./deployment/update-all.sh
```

## 📝 Notes

- All scripts are designed to be run from the project root directory
- Scripts automatically navigate to the correct directories
- Each script includes error handling and status reporting
- The Nginx configuration file is kept here for reference but is actively used from `/etc/nginx/sites-available/`

## 🔗 Related Files

- **`/DEPLOY.md`** - Initial deployment guide (in project root)
- **`/etc/nginx/sites-available/science-gpt.conf`** - Active Nginx config (symlinked)

## 🌐 Live Site

After running updates, your changes will be live at:
**https://sciencegptv2.canadacentral.cloudapp.azure.com**
