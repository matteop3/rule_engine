#!/bin/bash
# ==============================================================================
# Docker Entrypoint Script
# ==============================================================================
# This script runs database migrations before starting the application.
# It ensures the database schema is always up-to-date on container startup.
# ==============================================================================

set -e  # Exit on error

echo "=== Running database migrations ==="
alembic upgrade head

echo "=== Starting application ==="
exec "$@"
