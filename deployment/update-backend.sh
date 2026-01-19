#!/bin/bash
set -e

echo "🔄 Starting backend update..."

# Navigate to project root, then backend
cd "$(dirname "$0")/.."
cd backend

# Pull latest changes (skip if git repo not configured)
echo "📥 Checking for git repository..."
if git remote -v > /dev/null 2>&1 && git status > /dev/null 2>&1; then
    echo "📥 Pulling latest changes..."
    git pull origin main
else
    echo "⚠️  Git repository not configured, using local changes..."
fi

# Stop containers
echo "🛑 Stopping containers..."
docker compose down

# Rebuild containers
echo "🏗️ Rebuilding containers..."
docker compose build

# Start containers
echo "🚀 Starting containers..."
docker compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Show status
echo "✅ Backend update complete!"
docker compose ps

# Test health endpoint
echo "🔍 Testing health endpoint..."
curl -f http://localhost:8000/health || echo "❌ Health check failed"

echo "🌐 Your CAN-SR API has been updated!"
