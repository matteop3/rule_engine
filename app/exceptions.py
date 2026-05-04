"""
Custom exceptions for service layer.

These exceptions are raised by services and should be caught
by routers/handlers to convert them into appropriate HTTP responses.
"""


class ServiceError(Exception):
    """Base exception for service layer errors."""

    def __init__(self, message: str = "A service error occurred"):
        self.message = message
        super().__init__(self.message)
