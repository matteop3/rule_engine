"""
Rate Limiting configuration and utilities using slowapi.

This module provides rate limiting functionality for the API endpoints
to prevent abuse and brute force attacks.
"""

import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# RATE LIMITER SETUP
# ============================================================

def get_client_identifier(request: Request) -> str:
    """
    Get client identifier for rate limiting.

    Uses IP address by default. Can be extended to use:
    - User ID (for authenticated requests)
    - API key
    - Combination of factors

    Args:
        request: FastAPI request object

    Returns:
        str: Client identifier (IP address)
    """
    # For now, use IP address
    # In production, consider using X-Forwarded-For if behind a proxy
    client_ip = get_remote_address(request)

    # You can extend this to include user ID for authenticated requests:
    # if hasattr(request.state, "user"):
    #     return f"user:{request.state.user.id}"

    return client_ip


# Initialize the limiter
limiter = Limiter(
    key_func=get_client_identifier,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[],  # No default limits, apply per-endpoint
    storage_uri="memory://",  # In-memory storage (simple, single-instance)
)


# ============================================================
# RATE LIMIT EXCEPTION HANDLER
# ============================================================

def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a consistent JSON error response with appropriate HTTP status.

    Args:
        request: FastAPI request object
        exc: Rate limit exceeded exception

    Returns:
        JSONResponse: Error response with 429 status code
    """
    logger.warning(
        f"Rate limit exceeded for {get_client_identifier(request)} "
        f"on endpoint {request.url.path}"
    )

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "detail": "Too many requests. Please try again later.",
            "retry_after": getattr(exc, "detail", None)
        }
    )


# ============================================================
# RATE LIMIT STRINGS
# ============================================================

# These are the rate limit strings used by slowapi
# Format: "count/period" where period can be: second, minute, hour, day

def get_login_rate_limit() -> str:
    """Get rate limit string for login endpoint."""
    return f"{settings.RATE_LIMIT_LOGIN_ATTEMPTS}/{settings.RATE_LIMIT_LOGIN_WINDOW_MINUTES} minutes"


def get_refresh_rate_limit() -> str:
    """Get rate limit string for refresh endpoint."""
    return f"{settings.RATE_LIMIT_REFRESH_ATTEMPTS}/{settings.RATE_LIMIT_REFRESH_WINDOW_MINUTES} minutes"


def get_api_rate_limit() -> str:
    """Get rate limit string for general API endpoints."""
    return f"{settings.RATE_LIMIT_API_PER_MINUTE}/minute"
