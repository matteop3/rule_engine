import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.domain import User, RefreshToken
from app.core.security import (
    verify_password,
    create_refresh_token,
    hash_refresh_token,
    REFRESH_TOKEN_EXPIRE_DAYS
)

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

    def create_user_refresh_token(
        self,
        db: Session,
        user_id: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> tuple[str, RefreshToken]:
        """
        Create a new refresh token for a user and store it in the database.

        Args:
            db: Database session
            user_id: User ID to create token for
            user_agent: Optional user agent string for tracking
            ip_address: Optional IP address for tracking

        Returns:
            tuple: (plaintext_token, RefreshToken database record)

        Example:
            >>> token, db_record = auth_service.create_user_refresh_token(db, user.id)
            >>> # Return token to client, db_record is stored
        """
        # Generate secure random token
        plaintext_token = create_refresh_token()
        token_hash = hash_refresh_token(plaintext_token)

        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        # Create database record
        db_token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address
        )

        db.add(db_token)
        db.commit()
        db.refresh(db_token)

        logger.info(f"Created refresh token for user {user_id}, expires at {expires_at}")

        return plaintext_token, db_token

    def verify_user_refresh_token(
        self,
        db: Session,
        plaintext_token: str
    ) -> Optional[RefreshToken]:
        """
        Verify a refresh token and return the database record if valid.

        A token is valid if:
        1. It exists in the database
        2. It hasn't been revoked
        3. It hasn't expired
        4. The hash matches

        Args:
            db: Database session
            plaintext_token: The refresh token to verify

        Returns:
            RefreshToken record if valid, None otherwise
        """
        token_hash = hash_refresh_token(plaintext_token)

        # Find token in database
        db_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash
        ).first()

        if not db_token:
            logger.warning("Refresh token not found in database")
            return None

        # Check if revoked
        if db_token.is_revoked:
            logger.warning(f"Refresh token {db_token.id} has been revoked")
            return None

        # Check if expired
        now_utc = datetime.now(timezone.utc)
        # Handle timezone-naive datetimes from SQLite
        expires_at = db_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now_utc:
            logger.warning(f"Refresh token {db_token.id} has expired")
            return None

        # Update last used timestamp
        db_token.last_used_at = now_utc
        db.commit()

        logger.info(f"Refresh token {db_token.id} verified successfully for user {db_token.user_id}")

        return db_token

    def revoke_refresh_token(self, db: Session, token_id: int) -> bool:
        """
        Revoke a refresh token by its ID.

        Args:
            db: Database session
            token_id: ID of the refresh token to revoke

        Returns:
            bool: True if token was revoked, False if not found
        """
        db_token = db.query(RefreshToken).filter(RefreshToken.id == token_id).first()

        if not db_token:
            logger.warning(f"Cannot revoke: refresh token {token_id} not found")
            return False

        db_token.is_revoked = True
        db_token.revoked_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Revoked refresh token {token_id} for user {db_token.user_id}")

        return True

    def revoke_all_user_refresh_tokens(self, db: Session, user_id: str) -> int:
        """
        Revoke all active refresh tokens for a user.

        Useful for:
        - User logout from all devices
        - Password change
        - Security incident response

        Args:
            db: Database session
            user_id: User ID whose tokens to revoke

        Returns:
            int: Number of tokens revoked
        """
        now_utc = datetime.now(timezone.utc)

        result = db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked.is_(False)
        ).update({
            "is_revoked": True,
            "revoked_at": now_utc
        })

        db.commit()

        logger.info(f"Revoked {result} refresh tokens for user {user_id}")

        return result

    def cleanup_expired_tokens(self, db: Session) -> int:
        """
        Delete expired refresh tokens from the database.

        Should be run periodically (e.g., daily cron job) to keep database clean.

        Args:
            db: Database session

        Returns:
            int: Number of tokens deleted
        """
        now_utc = datetime.now(timezone.utc)

        result = db.query(RefreshToken).filter(
            RefreshToken.expires_at < now_utc
        ).delete()

        db.commit()

        logger.info(f"Cleaned up {result} expired refresh tokens")

        return result