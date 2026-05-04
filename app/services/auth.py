import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import REFRESH_TOKEN_EXPIRE_DAYS, create_refresh_token, hash_refresh_token, verify_password
from app.models.domain import RefreshToken, User

logger = logging.getLogger(__name__)


class AuthService:
    """Pure authentication logic."""

    def authenticate_user(self, db: Session, email: str, password: str) -> User | None:
        """Return the active `User` matching `(email, password)` or `None` for any failure mode."""
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
        self, db: Session, user_id: str, user_agent: str | None = None, ip_address: str | None = None
    ) -> tuple[str, RefreshToken]:
        """Persist a new refresh token; returns `(plaintext_token, RefreshToken)`.

        The plaintext is returned to the caller and never stored — only its hash lives in the DB.
        """
        # Generate secure random token
        plaintext_token = create_refresh_token()
        token_hash = hash_refresh_token(plaintext_token)

        # Calculate expiration
        expires_at = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        # Create database record
        db_token = RefreshToken(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at, user_agent=user_agent, ip_address=ip_address
        )

        db.add(db_token)
        db.commit()
        db.refresh(db_token)

        logger.info(f"Created refresh token for user {user_id}, expires at {expires_at}")

        return plaintext_token, db_token

    def verify_user_refresh_token(self, db: Session, plaintext_token: str) -> RefreshToken | None:
        """Return the matching `RefreshToken` if not revoked and not expired, else `None`.

        Updates `last_used_at` on success. Handles SQLite's naive `expires_at` by
        coercing to UTC before the comparison.
        """
        token_hash = hash_refresh_token(plaintext_token)

        # Find token in database
        db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

        if not db_token:
            logger.warning("Refresh token not found in database")
            return None

        # Check if revoked
        if db_token.is_revoked:
            logger.warning(f"Refresh token {db_token.id} has been revoked")
            return None

        # Check if expired
        now_utc = datetime.now(UTC)
        # Handle timezone-naive datetimes from SQLite
        expires_at = db_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now_utc:
            return None

        # Update last used timestamp
        db_token.last_used_at = now_utc
        db.commit()

        logger.info(f"Refresh token {db_token.id} verified successfully for user {db_token.user_id}")

        return db_token

    def revoke_refresh_token(self, db: Session, token_id: int) -> bool:
        """Mark `token_id` as revoked; returns `False` if it doesn't exist."""
        db_token = db.query(RefreshToken).filter(RefreshToken.id == token_id).first()

        if not db_token:
            return False

        db_token.is_revoked = True
        db_token.revoked_at = datetime.now(UTC)
        db.commit()

        logger.info(f"Revoked refresh token {token_id} for user {db_token.user_id}")

        return True

    def revoke_all_user_refresh_tokens(self, db: Session, user_id: str) -> int:
        """Revoke every active refresh token for `user_id`; returns the count."""
        now_utc = datetime.now(UTC)

        result = (
            db.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
            .update({"is_revoked": True, "revoked_at": now_utc})
        )

        db.commit()

        logger.info(f"Revoked {result} refresh tokens for user {user_id}")

        return result

    def cleanup_expired_tokens(self, db: Session) -> int:
        """Hard-delete every refresh token whose `expires_at` is in the past; returns the count."""
        now_utc = datetime.now(UTC)

        result = db.query(RefreshToken).filter(RefreshToken.expires_at < now_utc).delete()

        db.commit()

        logger.info(f"Cleaned up {result} expired refresh tokens")

        return result
