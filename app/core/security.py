import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return `True` when `plain_password` matches the bcrypt-hashed value from storage."""
    try:
        result = _bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
        if not result:
            logger.warning("Password verification failed: incorrect password")
        return result
    except Exception as e:
        logger.error(f"Password verification error: {str(e)}", exc_info=True)
        return False


def get_password_hash(password: str) -> str:
    """Return a bcrypt hash of `password` (with a fresh salt)."""
    try:
        hashed = _bcrypt.hashpw(
            password.encode("utf-8"),
            _bcrypt.gensalt(),
        ).decode("utf-8")
        return hashed
    except Exception as e:
        logger.error(f"Password hashing error: {str(e)}", exc_info=True)
        raise


def validate_password_policy(password: str) -> tuple[bool, str | None]:
    """Validate `password` against the `PASSWORD_*` policy in settings; returns `(ok, error_or_None)`."""
    # Check minimum length
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters long"

    # Check for uppercase letter
    if settings.PASSWORD_REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    # Check for lowercase letter
    if settings.PASSWORD_REQUIRE_LOWERCASE and not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"

    # Check for digit
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password):
        return False, "Password must contain at least one digit"

    # Check for special character
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"

    return True, None


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Sign and return a JWT for `subject` (usually a user id), expiring after `expires_delta`."""
    try:
        now_utc = datetime.now(UTC)

        if expires_delta:
            expire = now_utc + expires_delta
        else:
            expire = now_utc + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        # Token payload. 'sub' (subject) is a JWT standard to identify the user
        to_encode = {"exp": expire, "sub": str(subject)}

        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

        logger.debug(f"Access token created for subject {subject}, expires at {expire.isoformat()}")

        return str(encoded_jwt)
    except Exception as e:
        logger.error(f"Token creation error: {str(e)}", exc_info=True)
        raise


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT; returns the payload dict or `None` on signature/format error."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return dict(payload)
    except JWTError as e:
        logger.warning(f"Token decode error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected token decode error: {str(e)}", exc_info=True)
        return None


def verify_token_signature(token: str) -> bool:
    """Return `True` if `token` has a valid JWT signature, without using the payload."""
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except JWTError:
        return False


def create_refresh_token() -> str:
    """Return a cryptographically secure 64-hex-char random token (opaque, not a JWT)."""
    return secrets.token_hex(32)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest of `token`; refresh tokens are never stored in plaintext."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(token: str, token_hash: str) -> bool:
    """Constant-time check that `token` matches the stored `token_hash` (SHA-256)."""
    return secrets.compare_digest(hash_refresh_token(token), token_hash)
