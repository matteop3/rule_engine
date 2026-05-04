import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, get_user_or_404, get_user_service, require_role
from app.models.domain import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.users import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
    user_service: UserService = Depends(get_user_service),
):
    """
    Create a new user.
    ONLY ADMINS can create new users via API.
    """
    logger.info(f"Creating user with email: {user_in.email} by admin {current_user.id}")
    require_role(current_user, [UserRole.ADMIN])

    # Check if email already exists
    if user_service.get_by_email(db, user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists.",
        )

    # Create new User
    with db_transaction(db, f"create_user '{user_in.email}'"):
        new_user = user_service.create_user(db, user_in, current_user.id)

    db.refresh(new_user)

    logger.info(f"User {new_user.id} created successfully: email={user_in.email}, role={user_in.role.value}")

    return new_user


@router.get("/", response_model=list[UserRead])
def list_users(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
):
    """
    List all users.
    ONLY ADMINS can see the user list.
    """
    logger.info(f"Listing users by admin {current_user.id}: skip={skip}, limit={limit}")
    require_role(current_user, [UserRole.ADMIN])

    limit = min(limit, 100)

    users = db.query(User).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(users)} users")

    return users


@router.get("/me", response_model=UserRead)
def read_user_me(
    current_user: User = Depends(get_current_user),  # Auth required
):
    """
    Get current user profile.
    Accessible to any logged-in user.
    """
    logger.debug(f"User {current_user.id} retrieved own profile")
    return current_user


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user: User = Depends(get_user_or_404),
    current_user: User = Depends(get_current_user),  # Auth required
):
    """
    Get user by ID.
    ONLY ADMINS can view other users.
    """
    logger.info(f"Admin {current_user.id} retrieving user {user.id}")
    require_role(current_user, [UserRole.ADMIN])

    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_in: UserUpdate,
    user: User = Depends(get_user_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
    user_service: UserService = Depends(get_user_service),
):
    """
    Update user. Use this to BAN users (is_active=False) or change role.
    ONLY ADMINS can update users.
    """
    logger.info(f"Admin {current_user.id} updating user {user.id}")
    require_role(current_user, [UserRole.ADMIN])

    if user_in.email is not None and user_in.email != user.email:
        if user_service.get_by_email(db, user_in.email):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Email already in use.")

    with db_transaction(db, f"update_user {user.id}"):
        updated_user = user_service.update_user(db, user, user_in, current_user.id)

    db.refresh(updated_user)

    logger.info(f"User {user.id} updated successfully by admin {current_user.id}")

    return updated_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user: User = Depends(get_user_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth required
    user_service: UserService = Depends(get_user_service),
):
    """
    Disable a user (soft delete).
    ONLY ADMINS can delete users.
    """
    logger.info(f"Admin {current_user.id} deleting user {user.id}")
    require_role(current_user, [UserRole.ADMIN])

    if user.id == current_user.id:
        logger.warning(f"Admin {current_user.id} attempted to delete own account")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")

    with db_transaction(db, f"soft_delete_user {user.id}"):
        user_service.soft_delete_user(db, user, current_user.id)

    logger.info(f"User {user.id} soft-deleted successfully by admin {current_user.id}")

    return None
