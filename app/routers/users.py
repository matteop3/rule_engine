from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.core.security import get_password_hash

import uuid

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
        is_active=user_in.is_active,
        created_by_id=current_user.id,
        updated_by_id=current_user.id
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


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    require_role(current_user, [UserRole.ADMIN])
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Update user. Use this to BAN users (is_active=False) or change role. """
    require_role(current_user, [UserRole.ADMIN])
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    if user_in.email is not None and user_in.email != user.email:
        existing_email = db.query(User).filter(User.email == user_in.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Email already in use."
            )

    update_data = user_in.model_dump(exclude_unset=True)

    # Hash password, if needed
    if "password" in update_data:
        hashed = get_password_hash(update_data["password"])
        update_data["hashed_password"] = hashed
        del update_data["password"] # Blank plain text password

    for key, value in update_data.items():
        setattr(user, key, value)
    
    # Audit update
    user.updated_by_id = current_user.id

    db.commit()
    db.refresh(user)

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Disable a user.
    Blocked if the user has existing configurations.
    """
    require_role(current_user, [UserRole.ADMIN])
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Block to delete themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account."
        )

    # Soft-delete logic
    user.is_active = False

    # Rename the email to free it up and make it unusable but traceable
    # Use a short UUID to ensure uniqueness
    user.email = f"{user.email}_deleted_{str(uuid.uuid4())[:8]}"
    
    # Audit update
    user.updated_by_id = current_user.id

    db.commit()    
    # No refresh is needed because return 204 (no content).

    return None