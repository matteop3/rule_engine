.DEFAULT_GOAL := help

# Env vars needed by Settings() at import time (tests use testcontainers, not these values)
export DATABASE_URL ?= postgresql://rule_engine_user:rule_engine_password@localhost:5432/rule_engine_db
export SECRET_KEY ?= makefile-dummy-secret-key-only-for-local-dev-1234

# ── Docker ──────────────────────────────────────────────
.PHONY: up down build logs clean

up:           ## Start services in background
	docker compose up -d

down:         ## Stop services
	docker compose down

build:        ## Rebuild and start services
	docker compose up --build -d

logs:         ## Follow application logs
	docker compose logs -f app

clean:        ## Stop services and remove volumes
	docker compose down -v

# ── Development ─────────────────────────────────────────
.PHONY: seed migrate openapi

seed:         ## Load demo data into database
	python seed_data.py

migrate:      ## Run database migrations
	alembic upgrade head

openapi:      ## Regenerate openapi.json from source code
	python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json

# ── Quality ─────────────────────────────────────────────
.PHONY: lint format typecheck check

lint:         ## Run linter
	ruff check .

format:       ## Format code
	ruff format .

typecheck:    ## Run type checker
	mypy app/

check:        ## Run all quality checks (lint + format check + typecheck)
	ruff check .
	ruff format --check .
	mypy app/

# ── Tests ───────────────────────────────────────────────
.PHONY: test test-cov test-api test-engine

test:         ## Run all tests
	pytest -q

test-cov:     ## Run tests with HTML coverage report
	pytest --cov=app --cov-report=html

test-api:     ## Run API tests only
	pytest tests/api/ -q

test-engine:  ## Run engine tests only
	pytest tests/engine/ -q

# ── Help ────────────────────────────────────────────────
.PHONY: help

help:         ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
