from typing import Optional
from sqlalchemy.orm import Session
import uuid

from app.models.domain import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash

class UserService:
    def get_by_id(self, db: Session, user_id: str) -> Optional[User]:
        """ If exist, get User by its ID, None otherwise. """
        return db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        """ If exist, get User by its email, None otherwise. """
        return db.query(User).filter(User.email == email).first()

    def create_user(self, db: Session, user_in: UserCreate, creator_id: str) -> User:
        """ Create a new User. """
        new_user = User(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            role=user_in.role,
            is_active=user_in.is_active,
            created_by_id=creator_id,
            updated_by_id=creator_id
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    def update_user(self, db: Session, user: User, user_in: UserUpdate, updater_id: str) -> User:
        """ Update an existing user. """
        update_data = user_in.model_dump(exclude_unset=True)

        if "password" in update_data:
            hashed = get_password_hash(update_data["password"])
            update_data["hashed_password"] = hashed
            del update_data["password"]  # Blank plaintext password

        for key, value in update_data.items():
            setattr(user, key, value)
        
        user.updated_by_id = updater_id
        db.commit()
        db.refresh(user)
        
        return user

    def soft_delete_user(self, db: Session, user: User, deleter_id: str) -> None:
        """
        Deactivate user and randomize email to allow future reuse of the original email.
        """
        user.is_active = False
        # Rename email using short UUID
        user.email = f"{user.email}_deleted_{str(uuid.uuid4())[:8]}"
        user.updated_by_id = deleter_id
        db.commit()