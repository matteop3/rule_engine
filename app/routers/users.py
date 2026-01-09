from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.dependencies import get_current_user, require_role, get_user_service, get_user_or_404
from app.models.domain import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.core.security import get_password_hash
from app.services.users import UserService


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
    user_service: UserService = Depends(get_user_service)
):
    """
    Create a new user.
    ONLY ADMINS can create new users via API.
    """
    require_role(current_user, [UserRole.ADMIN])

    # Check if email already exists
    if user_service.get_by_email(db, user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists.",
        )
    
    # Create new User
    new_user = user_service.create_user(db, user_in, current_user.id)
    
    return new_user


@router.get("/", response_model=List[UserRead])
def list_users(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth required
):
    """
    List all users.
    ONLY ADMINS can see the user list.
    """
    require_role(current_user, [UserRole.ADMIN])
    
    limit = min(limit, 100)
    users = db.query(User).offset(skip).limit(limit).all()

    return users


@router.get("/me", response_model=UserRead)
def read_user_me(
    current_user: User = Depends(get_current_user)  # Auth required
):
    """
    Get current user profile.
    Accessible to any logged-in user.
    """
    return current_user


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user: User = Depends(get_user_or_404),
    current_user: User = Depends(get_current_user)  # Auth required
):
    require_role(current_user, [UserRole.ADMIN])
    
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_in: UserUpdate,
    user: User = Depends(get_user_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user), # Auth required
    user_service: UserService = Depends(get_user_service)
):
    """ Update user. Use this to BAN users (is_active=False) or change role. """
    require_role(current_user, [UserRole.ADMIN])

    if user_in.email is not None and user_in.email != user.email:
        if user_service.get_by_email(db, user_in.email):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Email already in use.")

    return user_service.update_user(db, user, user_in, current_user.id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user: User = Depends(get_user_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
    user_service: UserService = Depends(get_user_service)
):
    """ Disable a user. """
    require_role(current_user, [UserRole.ADMIN])

    if user.id == current_user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account."
        )

    user_service.soft_delete_user(db, user, current_user.id)
    return None