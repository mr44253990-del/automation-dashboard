#!/bin/bash
set -e

# Ensure config directory exists
mkdir -p /app/data /app/logs /app/screenshots /app/backups

# Initialize config if not exists
python3 -c "
from app.config import ensure_config
ensure_config()
print('Config initialized')
" 2>/dev/null || true

# Run database migrations or setup if needed
# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
