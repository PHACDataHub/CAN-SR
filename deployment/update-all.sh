#!/bin/bash
set -e

echo "🚀 Starting full application update..."

# Navigate to deployment directory
cd "$(dirname "$0")"

# Update backend first
echo "🔧 Updating backend..."
./update-backend.sh

# Update frontend
echo "🎨 Updating frontend..."
./update-frontend.sh

# Final verification
echo "🔍 Final verification..."
sleep 5

echo "Testing backend health endpoint..."
curl http://localhost:8000/health

echo "✅ Full CAN-SR update complete!"
echo "🌐 Backend services are running. Frontend is accessible via your configured domain."
