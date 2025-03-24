from datetime import datetime
from typing import Optional, List
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from common.database import Base


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class User(Base):
    """User model"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(sa.String, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(sa.String, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(sa.String, nullable=False)
    
    # User role
    role: Mapped[str] = mapped_column(
        sa.String, 
        default=UserRole.USER,
        server_default=UserRole.USER
    )
    
    # Gamification stats
    level: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")
    experience: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    
    # User status
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, 
        default=True,
        server_default=sa.text("true")
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), 
        server_default=func.now(),
        onupdate=func.now()
    )
    
    # Relationships
    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"User(id={self.id}, email={self.email}, username={self.username})"


class TokenType(str, Enum):
    REFRESH = "refresh"
    RESET_PASSWORD = "reset_password"
    EMAIL_VERIFICATION = "email_verification"


class Token(Base):
    """Token model for refresh tokens, password reset, etc."""
    __tablename__ = "tokens"
    
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(sa.String, unique=True, index=True, nullable=False)
    
    # Token type
    token_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    
    # Validity period
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    
    # Token status
    is_revoked: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.text("false"))
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Relationships
    user = relationship("User", back_populates="tokens")
    
    def __repr__(self) -> str:
        return f"Token(id={self.id}, user_id={self.user_id}, type={self.token_type})"