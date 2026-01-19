#!/bin/bash
set -e

echo "🔄 Starting frontend update..."

# Navigate to project root, then frontend
cd "$(dirname "$0")/.."
cd frontend

# Pull latest changes (skip if git repo not configured)
echo "📥 Checking for git repository..."
if git remote -v > /dev/null 2>&1 && git status > /dev/null 2>&1; then
    echo "📥 Pulling latest changes..."
    git pull origin main
else
    echo "⚠️  Git repository not configured, using local changes..."
fi

# Install dependencies
echo "📦 Installing dependencies..."
npm install

# Build production version
echo "🏗️ Building production version..."
npm run build

# Restart PM2 process
echo "🔄 Restarting PM2 process..."
pm2 restart can-sr-frontend

# Show status
echo "✅ Frontend update complete!"
pm2 status
pm2 logs can-sr-frontend --lines 10

echo "🌐 Your CAN-SR site has been updated!"
