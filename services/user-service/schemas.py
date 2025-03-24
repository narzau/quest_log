from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, EmailStr, Field, validator


class TokenPayload(BaseModel):
    """Payload for JWT token"""
    sub: str
    exp: int
    role: Optional[str] = None
    email: Optional[str] = None
    type: str = "access"


class TokenResponse(BaseModel):
    """Response with access and refresh tokens"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class TokenRefresh(BaseModel):
    """Request to refresh access token"""
    refresh_token: str


class UserCreate(BaseModel):
    """Schema for creating a new user"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """Schema for updating user data"""
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user response (public data)"""
    id: int
    email: str
    username: str
    role: str
    level: int
    experience: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserInDB(UserResponse):
    """Schema for user in database (internal data)"""
    hashed_password: str
    updated_at: datetime

    class Config:
        from_attributes = True


class UserList(BaseModel):
    """Schema for a list of users with pagination"""
    items: List[UserResponse]
    total: int
    page: int
    size: int
    pages: int


class UserProgressionUpdate(BaseModel):
    """Schema for updating user progression data"""
    level: Optional[int] = None
    experience: Optional[int] = None


class PasswordChange(BaseModel):
    """Schema for changing password"""
    current_password: str
    new_password: str = Field(..., min_length=8)


class PasswordReset(BaseModel):
    """Schema for resetting password"""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema for confirming password reset"""
    token: str
    new_password: str = Field(..., min_length=8)