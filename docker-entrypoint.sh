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

# Seed demo data if the database is empty (first deploy only)
echo "=== Checking for demo data ==="
python -c "
from app.database import SessionLocal
from app.models.domain import Entity
db = SessionLocal()
count = db.query(Entity).count()
db.close()
if count == 0:
    print('No data found — seeding demo data...')
    import seed_data
    seed_data.seed_db()
else:
    print(f'Database already has {count} entity(ies) — skipping seed.')
"

echo "=== Starting application ==="
exec "$@"
