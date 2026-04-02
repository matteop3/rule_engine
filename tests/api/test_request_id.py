"""Tests for the RequestID middleware and structured logging filter."""

import logging
import uuid

from app.core.logging import RequestIDFilter, request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"


class TestRequestIDMiddleware:
    """Verify that every response carries a correlation ID."""

    def test_response_includes_request_id_header(self, client):
        """Any endpoint response contains X-Request-ID header."""
        response = client.get("/")
        assert REQUEST_ID_HEADER in response.headers

    def test_request_id_is_valid_uuid(self, client):
        """Auto-generated X-Request-ID is a valid UUID4."""
        response = client.get("/")
        rid = response.headers[REQUEST_ID_HEADER]
        parsed = uuid.UUID(rid, version=4)
        assert str(parsed) == rid

    def test_client_provided_request_id_is_echoed(self, client):
        """Sending X-Request-ID: custom-123 gets the same value back."""
        custom_id = "custom-correlation-id-123"
        response = client.get("/", headers={REQUEST_ID_HEADER: custom_id})
        assert response.headers[REQUEST_ID_HEADER] == custom_id

    def test_different_requests_get_different_ids(self, client):
        """Two sequential requests produce distinct IDs."""
        r1 = client.get("/")
        r2 = client.get("/")
        assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]

    def test_error_response_includes_request_id(self, client):
        """A 404 response still carries the X-Request-ID header."""
        response = client.get("/nonexistent-endpoint")
        assert REQUEST_ID_HEADER in response.headers


class TestRequestIDFilter:
    """Verify the logging filter injects request_id into log records."""

    def test_filter_injects_request_id_from_context(self):
        """RequestIDFilter sets record.request_id from request_id_ctx."""
        rid = "test-rid-abc"
        token = request_id_ctx.set(rid)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            filt = RequestIDFilter()
            filt.filter(record)
            assert record.request_id == rid  # type: ignore[attr-defined]
        finally:
            request_id_ctx.reset(token)

    def test_filter_returns_none_when_no_context(self):
        """Without an active context, request_id defaults to None."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        filt = RequestIDFilter()
        filt.filter(record)
        assert record.request_id is None  # type: ignore[attr-defined]
