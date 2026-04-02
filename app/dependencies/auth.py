"""Authentication & authorization dependencies."""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY
from app.database import get_db
from app.dependencies.fetchers import fetch_user_by_id
from app.models.domain import User, UserRole

logger = logging.getLogger(__name__)

# Define where is the login url (used by Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """
    Decode the token, extract the user ID (sub), and retrieve the user from DB.
    If something goes wrong, throw 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")

        if user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception from None

    # Fetch User from DB
    user = fetch_user_by_id(db, user_id)
    if not user:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user.")

    return user


def require_role(user: User, allowed_roles: list[UserRole]) -> None:
    """
    Check if User has an allowed role.
    If not, throw 403.
    """
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permissions to perform this action."
        )


def require_admin_or_author(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency that enforces ADMIN or AUTHOR role.

    Raises:
        HTTPException(403): If user is not ADMIN or AUTHOR

    Returns:
        User: The authenticated user with valid role
    """
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    return current_user
