import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.domain import User
from app.core.security import verify_password

logger = logging.getLogger(__name__)


class AuthService:
    """Pure authentication logic."""

    def authenticate_user(self, db: Session, email: str, password: str) -> Optional[User]:
        """
        Verify user credentials.
        Return User object if valid and active, None otherwise.

        Args:
            db: Database session
            email: User email
            password: Plain text password

        Returns:
            User object if authentication succeeds, None otherwise

        Note:
            Returns None for all failure cases (security best practice).
            Specific failure reasons are logged internally.
        """
        # Search for User
        user = db.query(User).filter(User.email == email).first()

        # Verify User existence
        if not user:
            logger.debug(f"Authentication failed: user not found for email {email}")
            return None

        # Verify User credentials
        if not verify_password(password, user.hashed_password):
            logger.warning(f"Authentication failed: invalid password for user {user.id} (email: {email})")
            return None

        # Verify if the User is active
        if not user.is_active:
            logger.warning(f"Authentication failed: user {user.id} is inactive (email: {email})")
            return None

        logger.debug(f"Authentication successful for user {user.id} (email: {email})")
        return user