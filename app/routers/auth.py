# app/routers/auth.py
import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import get_login_rate_limit, get_refresh_rate_limit, limiter
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.database import get_db
from app.dependencies import db_transaction, get_auth_service
from app.services.auth import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Security scheme for refresh token endpoint
http_bearer = HTTPBearer()


@router.post("/token")
@limiter.limit(get_login_rate_limit())
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    user_agent: str | None = Header(None),
):
    """OAuth2 password-grant login; returns `access_token` and `refresh_token`. Rate-limited."""
    logger.info(f"Login attempt for email: {form_data.username}")

    # Invoke auth service
    user = auth_service.authenticate_user(db=db, email=form_data.username, password=form_data.password)

    # If not found or not correct
    if not user:
        logger.warning(f"Failed login attempt for email: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email and/or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)

    # Generate refresh token
    client_ip = request.client.host if request.client else None
    with db_transaction(db, "issue_refresh_token"):
        refresh_token, _ = auth_service.create_user_refresh_token(
            db=db, user_id=user.id, user_agent=user_agent, ip_address=client_ip
        )

    logger.info(f"Successful login for user {user.id} (email: {form_data.username})")

    # Return both tokens
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh")
@limiter.limit(get_refresh_rate_limit())
async def refresh_access_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Issue a new access token from a refresh token (sent as `Authorization: Bearer ...`).

    When `REFRESH_TOKEN_ROTATION=true` the old refresh token is revoked and a
    new one is returned alongside the access token. Rate-limited.
    """
    refresh_token = credentials.credentials

    operation = "rotate_refresh_token" if settings.REFRESH_TOKEN_ROTATION else "verify_refresh_token"
    new_refresh_token: str | None = None
    # Verify, revoke-and-create are wrapped in a single transaction so a token
    # rotation is atomic: a crash mid-rotation leaves the caller with the
    # original token still valid, never with no token.
    with db_transaction(db, operation):
        db_token = auth_service.verify_user_refresh_token(db=db, plaintext_token=refresh_token)

        if not db_token:
            logger.warning("Invalid or expired refresh token used")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        from app.models.domain import User

        user = db.query(User).filter(User.id == db_token.user_id).first()

        if not user or not user.is_active:
            logger.warning(f"Refresh token user {db_token.user_id} not found or inactive")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)

        if settings.REFRESH_TOKEN_ROTATION:
            auth_service.revoke_refresh_token(db=db, token_id=db_token.id)
            new_refresh_token, _ = auth_service.create_user_refresh_token(
                db=db, user_id=user.id, user_agent=db_token.user_agent, ip_address=db_token.ip_address
            )

    logger.info(f"Access token refreshed for user {user.id}")

    if new_refresh_token is not None:
        logger.info(f"Refresh token rotated for user {user.id}")
        return {"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}

    return {"access_token": access_token, "token_type": "bearer"}
