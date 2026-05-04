import logging
import uuid

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.domain import User
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """Service layer for user management operations.

    Caller owns the transaction; this service does not commit or rollback.
    """

    def get_by_id(self, db: Session, user_id: str) -> User | None:
        """Return the `User` with matching `id` or `None`."""
        return db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, db: Session, email: str) -> User | None:
        """Return the `User` with matching `email` or `None`."""
        return db.query(User).filter(User.email == email).first()

    def create_user(self, db: Session, user_in: UserCreate, creator_id: str) -> User:
        """Create a `User` with bcrypt-hashed password; flushes so the generated id is populated."""
        logger.info(f"Creating new user: email={user_in.email}, role={user_in.role.value}")

        new_user = User(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            role=user_in.role,
            is_active=user_in.is_active,
            created_by_id=creator_id,
            updated_by_id=creator_id,
        )
        db.add(new_user)
        db.flush()

        logger.info(f"User created successfully: id={new_user.id}, email={user_in.email}")
        return new_user

    def update_user(self, db: Session, user: User, user_in: UserUpdate, updater_id: str) -> User:
        """Apply `user_in` to `user`; rehashes `password` if present."""
        logger.info(f"Updating user {user.id}")

        update_data = user_in.model_dump(exclude_unset=True)

        if "password" in update_data:
            hashed = get_password_hash(update_data["password"])
            update_data["hashed_password"] = hashed
            del update_data["password"]  # Blank plaintext password

        for key, value in update_data.items():
            setattr(user, key, value)

        user.updated_by_id = updater_id
        db.flush()

        logger.info(f"User {user.id} updated successfully")
        return user

    def soft_delete_user(self, db: Session, user: User, deleter_id: str) -> None:
        """Deactivate `user` and rewrite its email to `<email>_deleted_<uuid8>` so the original is reusable."""
        original_email = user.email
        logger.info(f"Soft-deleting user {user.id} (email: {original_email})")

        user.is_active = False
        # Rename email using short UUID
        user.email = f"{user.email}_deleted_{str(uuid.uuid4())[:8]}"
        user.updated_by_id = deleter_id
        db.flush()

        logger.info(
            f"User {user.id} soft-deleted successfully: original_email={original_email}, new_email={user.email}"
        )
