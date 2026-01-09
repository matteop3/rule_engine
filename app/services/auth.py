from typing import Optional
from sqlalchemy.orm import Session
from app.models.domain import User
from app.core.security import verify_password

class AuthService:
    """ Pure authentication logic. """

    def authenticate_user(self, db: Session, email: str, password: str) -> Optional[User]:
        """
        Verify user credentials.
        Return User object if valid and active, None otherwise.
        """
        # Search for User
        user = db.query(User).filter(User.email == email).first()
        
        # Verify User existence
        if not user:
            return None
        
        # Verify User credentials
        if not verify_password(password, user.hashed_password):
            return None
            
        # Verify if the User is active
        if not user.is_active:
            return None
            
        return user