"""ASGI middleware that assigns a correlation ID to each request."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generates or propagates a unique request ID for every HTTP request.

    If the client sends an ``X-Request-ID`` header, the same value is reused;
    otherwise a new UUID4 is generated.  The ID is stored in a context variable
    so that the logging filter can attach it to every log record, and it is
    echoed back in the response headers for client-side correlation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            request_id_ctx.reset(token)
