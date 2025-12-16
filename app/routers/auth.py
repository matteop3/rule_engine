# app/routers/auth.py
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.domain import User
from app.core.security import verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

@router.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db)
):
    """
    Standard OAuth2 endpoint to obtain the token.
    'username' (email) and 'password' required by Form Data.
    """
    # Find User by email (form_data.username)
    user = db.query(User).filter(User.email == form_data.username).first()
    
    # Verify User existence and check password
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email and/or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user.")

    # Generate the token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, # Put UUID into token
        expires_delta=access_token_expires
    )
    
    # Return standard JSON
    return {"access_token": access_token, "token_type": "bearer"}