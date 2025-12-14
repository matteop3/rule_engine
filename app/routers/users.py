from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import User, UserRole
from app.schemas.user import UserCreate, UserRead
from app.core.security import get_password_hash

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Create a new user.
    ONLY ADMINS can create new users via API.
    """
    require_role(current_user, [UserRole.ADMIN])

    # Check if email already exists
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists in the system.",
        )
    
    # Create new User
    new_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
        is_active=user_in.is_active
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@router.get("/", response_model=List[UserRead])
def list_users(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    List all users.
    ONLY ADMINS can see the user list.
    """
    require_role(current_user, [UserRole.ADMIN])
    
    users = db.query(User).offset(skip).limit(limit).all()
    return users


@router.get("/me", response_model=UserRead)
def read_user_me(
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Get current user profile.
    Accessible to any logged-in user.
    """
    return current_user