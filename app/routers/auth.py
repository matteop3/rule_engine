# app/routers/auth.py
import logging
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.services.auth import AuthService
from app.dependencies import get_auth_service


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Standard OAuth2 endpoint to obtain the token.

    Authenticates user with email/password and returns JWT token.
    """
    logger.info(f"Login attempt for email: {form_data.username}")

    # Invoke auth service
    user = auth_service.authenticate_user(
        db=db,
        email=form_data.username,
        password=form_data.password
    )

    # If not found or not correct
    if not user:
        logger.warning(f"Failed login attempt for email: {form_data.username}")
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

    logger.info(f"Successful login for user {user.id} (email: {form_data.username})")

    # Return standard JSON
    return {"access_token": access_token, "token_type": "bearer"}