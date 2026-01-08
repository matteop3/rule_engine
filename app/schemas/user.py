from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.models.domain import UserRole
from .base_schema import AuditSchemaMixin

# Base properties shared by models
class UserBase(BaseModel):
    email: EmailStr
    is_active: bool = True
    role: UserRole = UserRole.USER

# Properties to receive on user creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, description="Password must be at least 8 characters.")

# Properties to return to client
class UserRead(UserBase, AuditSchemaMixin):
    id: str
    
    class Config:
        from_attributes = True

# Schema for updating user (optional, for admin)
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None