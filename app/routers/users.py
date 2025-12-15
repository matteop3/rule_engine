from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import User, UserRole, Configuration
from app.schemas.user import UserCreate, UserRead, UserUpdate
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

    update_data = user_in.model_dump(exclude_unset=True)

    # Hash password, if needed
    if "password" in update_data:
        hashed = get_password_hash(update_data["password"])
        update_data["hashed_password"] = hashed
        del update_data["password"] # Blank plain text password

    for key, value in update_data.items():
        setattr(user, key, value)

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
    Delete a user permanently.
    Blocked if the user has existing configurations.
    To remove access without losing data, use PATCH is_active=False.
    """
    require_role(current_user, [UserRole.ADMIN])
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Guardrail: check if Configurations related to the User exist
    configs_count = db.query(Configuration).filter(Configuration.user_id == user_id).count()
    if configs_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete User because they own {configs_count} configurations. "
                "Please soft-delete the User (set is_active=False) to preserve data history."
            )
        )

    # Block to delete themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account."
        )

    db.delete(user)
    db.commit()

    return None