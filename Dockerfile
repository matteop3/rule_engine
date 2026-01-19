# ==============================================================================
# Rule Engine API - Dockerfile
# ==============================================================================

FROM python:3.12-slim

LABEL maintainer="matteop3"
LABEL description="Rule Engine API"

# Python configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_WARNING=1

WORKDIR /app

# System dependencies required for psycopg2 (PostgreSQL driver)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (copied first to leverage Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source code
COPY . .

# Make entrypoint script executable
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# Entrypoint runs migrations before starting the app
ENTRYPOINT ["./docker-entrypoint.sh"]

# Default command for production
# Override with docker-compose command for development (adds --reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
