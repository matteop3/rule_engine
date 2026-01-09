# app/routers/auth.py
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.services.auth import AuthService
from app.dependencies import get_auth_service

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ============================================================
# CRUD endpoints
# ============================================================

@router.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """ Standard OAuth2 endpoint to obtain the token. """
    
    # Invoke auth service
    user = auth_service.authenticate_user(
        db=db, 
        email=form_data.username, 
        password=form_data.password
    )
    
    # If not found or not correct
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email and/or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate the token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires
    )
    
    # Return standard JSON
    return {"access_token": access_token, "token_type": "bearer"}