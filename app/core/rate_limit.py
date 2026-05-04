"""Rate limiting configuration and utilities using slowapi."""

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """Return the client identifier used for rate limiting (currently the remote IP)."""
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_client_identifier,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[],  # No default limits, apply per-endpoint
    storage_uri="memory://",  # In-memory storage (simple, single-instance)
)


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a consistent 429 JSON response for slowapi rate-limit-exceeded errors."""
    logger.warning(f"Rate limit exceeded for {get_client_identifier(request)} on endpoint {request.url.path}")

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "detail": "Too many requests. Please try again later.",
            "retry_after": getattr(exc, "detail", None),
        },
    )


def get_login_rate_limit() -> str:
    """Get rate limit string for login endpoint."""
    return f"{settings.RATE_LIMIT_LOGIN_ATTEMPTS}/{settings.RATE_LIMIT_LOGIN_WINDOW_MINUTES} minutes"


def get_refresh_rate_limit() -> str:
    """Get rate limit string for refresh endpoint."""
    return f"{settings.RATE_LIMIT_REFRESH_ATTEMPTS}/{settings.RATE_LIMIT_REFRESH_WINDOW_MINUTES} minutes"


def get_api_rate_limit() -> str:
    """Get rate limit string for general API endpoints."""
    return f"{settings.RATE_LIMIT_API_PER_MINUTE}/minute"
