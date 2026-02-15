import logging
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.exceptions import DatabaseError
from app.models.domain import User
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """Service layer for user management operations."""

    def get_by_id(self, db: Session, user_id: str) -> User | None:
        """
        Get User by its ID.

        Args:
            db: Database session
            user_id: User ID to search for

        Returns:
            User object if found, None otherwise
        """
        logger.debug(f"Fetching user by id: {user_id}")
        return db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, db: Session, email: str) -> User | None:
        """
        Get User by its email.

        Args:
            db: Database session
            email: User email to search for

        Returns:
            User object if found, None otherwise
        """
        logger.debug(f"Fetching user by email: {email}")
        return db.query(User).filter(User.email == email).first()

    def create_user(self, db: Session, user_in: UserCreate, creator_id: str) -> User:
        """
        Create a new User.

        Args:
            db: Database session
            user_in: User creation data
            creator_id: ID of the user creating this user

        Returns:
            The newly created User object

        Raises:
            DatabaseError: On database errors
        """
        logger.info(f"Creating new user: email={user_in.email}, role={user_in.role.value}")

        try:
            new_user = User(
                email=user_in.email,
                hashed_password=get_password_hash(user_in.password),
                role=user_in.role,
                is_active=user_in.is_active,
                created_by_id=creator_id,
                updated_by_id=creator_id,
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            logger.info(f"User created successfully: id={new_user.id}, email={user_in.email}")
            return new_user

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating user: {str(e)}", exc_info=True)
            raise DatabaseError("Failed to create user") from None

    def update_user(self, db: Session, user: User, user_in: UserUpdate, updater_id: str) -> User:
        """
        Update an existing user.

        Args:
            db: Database session
            user: User object to update
            user_in: Update data
            updater_id: ID of the user performing the update

        Returns:
            The updated User object

        Raises:
            DatabaseError: On database errors
        """
        logger.info(f"Updating user {user.id}")

        try:
            update_data = user_in.model_dump(exclude_unset=True)

            if "password" in update_data:
                logger.debug(f"Updating password for user {user.id}")
                hashed = get_password_hash(update_data["password"])
                update_data["hashed_password"] = hashed
                del update_data["password"]  # Blank plaintext password

            for key, value in update_data.items():
                setattr(user, key, value)

            user.updated_by_id = updater_id
            db.commit()
            db.refresh(user)

            logger.info(f"User {user.id} updated successfully")
            return user

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error updating user {user.id}: {str(e)}", exc_info=True)
            raise DatabaseError("Failed to update user") from None

    def soft_delete_user(self, db: Session, user: User, deleter_id: str) -> None:
        """
        Deactivate user and randomize email to allow future reuse of the original email.

        Args:
            db: Database session
            user: User object to soft delete
            deleter_id: ID of the user performing the deletion

        Raises:
            DatabaseError: On database errors
        """
        original_email = user.email
        logger.info(f"Soft-deleting user {user.id} (email: {original_email})")

        try:
            user.is_active = False
            # Rename email using short UUID
            user.email = f"{user.email}_deleted_{str(uuid.uuid4())[:8]}"
            user.updated_by_id = deleter_id
            db.commit()

            logger.info(
                f"User {user.id} soft-deleted successfully: original_email={original_email}, new_email={user.email}"
            )

        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error soft-deleting user {user.id}: {str(e)}", exc_info=True)
            raise DatabaseError("Failed to delete user") from None
