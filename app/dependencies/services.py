"""Service factories and transaction helper."""

import logging
from contextlib import contextmanager
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.auth import AuthService
from app.services.rule_engine import RuleEngineService
from app.services.users import UserService
from app.services.versioning import VersioningService

logger = logging.getLogger(__name__)


@contextmanager
def db_transaction(db: Session, operation: str):
    """
    Context manager for safe database transactions with automatic rollback.

    Args:
        db: Database session
        operation: Description of the operation (for logging)

    Yields:
        Session: The database session

    Raises:
        HTTPException(500): On database errors
    """
    try:
        yield db
        db.commit()
        logger.info(f"Transaction committed successfully: {operation}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during {operation}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        ) from None


@lru_cache
def get_auth_service() -> AuthService:
    """
    Factory for Auth Service.
    Singleton pattern via @lru_cache.
    """
    return AuthService()


@lru_cache
def get_user_service() -> UserService:
    """
    Factory for User Service.
    Singleton pattern via @lru_cache.
    """
    return UserService()


@lru_cache
def get_rule_engine_service() -> RuleEngineService:
    """
    Factory for Rule Engine Service.
    Singleton pattern via @lru_cache.
    """
    return RuleEngineService()


@lru_cache
def get_versioning_service() -> VersioningService:
    """
    Factory for Versioning Service.
    Singleton pattern via @lru_cache.
    """
    return VersioningService()
