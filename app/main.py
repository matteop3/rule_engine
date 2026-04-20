from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.middleware.request_id import RequestIDMiddleware
from app.routers import (
    auth,
    bom_item_rules,
    bom_items,
    catalog_items,
    configuration_custom_items,
    configurations,
    entities,
    fields,
    price_list_items,
    price_lists,
    rules,
    users,
    values,
    versions,
)
from app.routers import engine as engine_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    This replaces the old @app.on_event("startup") and @app.on_event("shutdown").
    Code before 'yield' runs at startup, code after 'yield' runs at shutdown.

    Database schema is managed by Alembic migrations (see docker-entrypoint.sh).
    The entrypoint runs 'alembic upgrade head' before starting the application.
    """
    # === STARTUP ===
    # Database migrations are handled by Alembic via docker-entrypoint.sh
    # No create_all() needed - schema is managed through version-controlled migrations

    setup_logging(level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    yield  # App is running here

    # === SHUTDOWN ===
    # (nothing to clean up for now, but you could close connections here)


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,  # Register lifespan handler
)

# Middleware (order matters: outermost middleware runs first)
app.add_middleware(RequestIDMiddleware)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Router registration
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(entities.router)
app.include_router(versions.router)
app.include_router(fields.router)
app.include_router(values.router)
app.include_router(rules.router)
app.include_router(bom_items.router)
app.include_router(bom_item_rules.router)
app.include_router(engine_router.router)
app.include_router(configurations.router)
app.include_router(price_lists.router)
app.include_router(price_list_items.router)
app.include_router(catalog_items.router)
app.include_router(configuration_custom_items.router)


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok", "message": f"{settings.PROJECT_NAME} is running"}
