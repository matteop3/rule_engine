import logging
import re
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any, Dict

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


# ============================================================
# PASSWORD CONTEXT
# ============================================================

# Password hashing using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================
# PASSWORD FUNCTIONS
# ============================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Compare plaintext password with hashed password from DB.

    Args:
        plain_password: The plaintext password to verify
        hashed_password: The hashed password from database

    Returns:
        bool: True if passwords match, False otherwise
    """
    try:
        result = pwd_context.verify(plain_password, hashed_password)
        if result:
            logger.debug("Password verification successful")
        else:
            logger.warning("Password verification failed: incorrect password")
        return result
    except Exception as e:
        logger.error(f"Password verification error: {str(e)}", exc_info=True)
        return False


def get_password_hash(password: str) -> str:
    """
    Generate a secure hash from plaintext password.

    Args:
        password: The plaintext password to hash

    Returns:
        str: The hashed password
    """
    try:
        hashed = pwd_context.hash(password)
        logger.debug("Password hashed successfully")
        return hashed
    except Exception as e:
        logger.error(f"Password hashing error: {str(e)}", exc_info=True)
        raise


def validate_password_policy(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password against security policy defined in settings.

    Args:
        password: The plaintext password to validate

    Returns:
        tuple: (is_valid: bool, error_message: Optional[str])

    Example:
        >>> valid, error = validate_password_policy("MyPass123!")
        >>> if not valid:
        ...     print(error)
    """
    # Check minimum length
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters long"

    # Check for uppercase letter
    if settings.PASSWORD_REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"

    # Check for lowercase letter
    if settings.PASSWORD_REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"

    # Check for digit
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, "Password must contain at least one digit"

    # Check for special character
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"

    logger.debug("Password policy validation passed")
    return True, None


# ============================================================
# JWT TOKEN FUNCTIONS
# ============================================================

def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Generate a signed JWT access token.

    Args:
        subject: The subject (usually user ID or email) to encode in the token
        expires_delta: Optional custom expiration time. If not provided, uses default from settings

    Returns:
        str: The encoded JWT token

    Example:
        >>> token = create_access_token(subject="user123")
        >>> token = create_access_token(subject="user123", expires_delta=timedelta(hours=1))
    """
    try:
        now_utc = datetime.now(timezone.utc)

        if expires_delta:
            expire = now_utc + expires_delta
        else:
            expire = now_utc + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        # Token payload. 'sub' (subject) is a JWT standard to identify the user
        to_encode = {"exp": expire, "sub": str(subject)}

        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

        logger.info(f"Access token created for subject: {subject}")
        logger.debug(f"Token expires at: {expire.isoformat()}")

        return encoded_jwt
    except Exception as e:
        logger.error(f"Token creation error: {str(e)}", exc_info=True)
        raise


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT access token.

    Args:
        token: The JWT token string to decode

    Returns:
        Optional[Dict]: The decoded token payload if valid, None if invalid

    Example:
        >>> payload = decode_access_token(token)
        >>> if payload:
        ...     user_id = payload.get("sub")
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        logger.debug(f"Token decoded successfully for subject: {payload.get('sub')}")

        return payload
    except JWTError as e:
        logger.warning(f"Token decode error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected token decode error: {str(e)}", exc_info=True)
        return None


def verify_token_signature(token: str) -> bool:
    """
    Verify the signature of a JWT token without decoding the full payload.
    Useful for quick token validation checks.

    Args:
        token: The JWT token to verify

    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except JWTError:
        return False


# ============================================================
# REFRESH TOKEN FUNCTIONS
# ============================================================

def create_refresh_token() -> str:
    """
    Generate a secure random refresh token (not JWT).

    Returns:
        str: A cryptographically secure random token string (64 hex characters)

    Example:
        >>> token = create_refresh_token()
        >>> len(token)
        64
    """
    token = secrets.token_hex(32)
    logger.debug("Refresh token generated")
    return token


def hash_refresh_token(token: str) -> str:
    """
    Create a SHA-256 hash of a refresh token for secure storage.

    We never store refresh tokens in plaintext, only their hashes.
    This prevents token theft if the database is compromised.

    Args:
        token: The plaintext refresh token to hash

    Returns:
        str: The hex-encoded SHA-256 hash of the token

    Example:
        >>> token = "abc123"
        >>> hashed = hash_refresh_token(token)
        >>> len(hashed)
        64
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(token: str, token_hash: str) -> bool:
    """
    Verify that a plaintext refresh token matches its stored hash.

    Args:
        token: The plaintext refresh token to verify
        token_hash: The stored hash to compare against

    Returns:
        bool: True if the token matches the hash, False otherwise

    Example:
        >>> token = "abc123"
        >>> hashed = hash_refresh_token(token)
        >>> verify_refresh_token(token, hashed)
        True
        >>> verify_refresh_token("wrong", hashed)
        False
    """
    computed_hash = hash_refresh_token(token)
    return secrets.compare_digest(computed_hash, token_hash)
