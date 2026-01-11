from typing import Optional
from pydantic import EmailStr, Field
from app.models.domain import UserRole
from .base_schema import BaseSchema, AuditSchemaMixin


class UserBase(BaseSchema):
    """Base properties shared by all User schemas."""
    email: EmailStr
    is_active: bool = True
    role: UserRole = UserRole.USER


class UserCreate(UserBase):
    """Schema for creating a new user (POST)."""
    password: str = Field(min_length=8, description="Password must be at least 8 characters.")


class UserRead(UserBase, AuditSchemaMixin):
    """Schema for reading user data (GET responses)."""
    id: str


class UserUpdate(BaseSchema):
    """Schema for updating user (PATCH). All fields optional."""
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None