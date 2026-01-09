"""
Global Dependencies for the API.

This module acts as a central catalog for all dependency injections used in Routers.
It includes:
1. Authentication & Authorization (User retrieval, Role checks)
2. Service Factories
3. Domain Logic & Validation (Entity retrieval, Version checks)
"""

from typing import Optional, List, Annotated
from functools import lru_cache

from fastapi import Depends, HTTPException, status, Path
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth import AuthService
from app.models.domain import User, UserRole, EntityVersion, VersionStatus
from app.core.security import SECRET_KEY, ALGORITHM
from app.services.rule_engine import RuleEngineService
from app.services.users import UserService


# ============================================================
# AUTHENTICATION & SECURITY
# ============================================================

# Define where is the login url (used by Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
) -> User:
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
        user_id: Optional[str] = payload.get("sub")
        
        if user_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception

    # Fetch User from DB
    user = db.query(User).filter(User.id == user_id).first()
        
    if user is None:
        raise credentials_exception
        
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user.")

    return user


def require_role(user: User, allowed_roles: List[UserRole]):
    """
    Check if User has an allowed role.
    If not, throw 403.
    """
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permissions to perform this action."
        )


# ============================================================
# SERVICE FACTORIES
# ============================================================

@lru_cache()
def get_auth_service() -> AuthService:
    """
    Factory for Auth Service.
    Singleton pattern via @lru_cache.
    """
    return AuthService()

@lru_cache()
def get_user_service() -> UserService:
    """
    Factory for User Service.
    Singleton pattern via @lru_cache.
    """
    return UserService()

@lru_cache()
def get_rule_engine_service() -> RuleEngineService:
    """
    Factory for Rule Engine Service.
    Singleton pattern via @lru_cache.
    """
    return RuleEngineService()


# ============================================================
# DOMAIN HELPERS (Pure logic)
# ============================================================

def fetch_user_by_id(db: Session, user_id: str) -> User:
    """
    Helper: Get aUser by its ID.    
    Raises: 
        HTTPException(404): If not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"User {user_id} not found."
        )
    return user

def validate_version_is_draft(version: EntityVersion) -> None:
    """
    Helper: Validates a version is DRAFT.    
    Raises: 
        HTTPException(409): If not DRAFT
    """
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Version {version.id} is {version.status.value}. "
                "Only DRAFT versions can be modified. "
                "Clone this version to make changes."
            )
        )
    
def fetch_version_by_id(db: Session, version_id: int) -> EntityVersion:
    """
    Fetch a Version object by its ID.
    Raises: 
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if version_id <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid ID")

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity Version {version_id} not found."
        )
    return version


# ============================================================
# VERSIONS DEPENDENCIES (HTTP context)
# ============================================================

def get_version_or_404(
    version_id: Annotated[int, Path(description="Entity Version ID", gt=0)],
    db: Session = Depends(get_db)
) -> EntityVersion:
    """
    Dependency: Retrieves an EntityVersion by ID.    
    Raises:
        HTTPException(404): If version doesn't exist
    """
    return fetch_version_by_id(db, version_id)

def get_editable_version(
    version: EntityVersion = Depends(get_version_or_404)
) -> EntityVersion:
    """
    Dependency: Retrieves a DRAFT EntityVersion.
    
    It reuses 'get_version_or_404' to fetch the object,
    then applies the status validation.
    """
    validate_version_is_draft(version)
    return version


# ============================================================
# USERS DEPENDENCIES (HTTP context)
# ============================================================

def get_user_or_404(
    user_id: str,
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency: Fetch user from Path ID.    
    Raises:
        HTTPException(404): If User doesn't exist or isn't active.
    """
    return fetch_user_by_id(db, user_id)