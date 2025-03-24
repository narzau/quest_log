import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union

from sqlalchemy import select, update, delete, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import BaseRepository, AsyncDatabase
from models import User, Token, TokenType
from common.monitoring import track_db_query
from common.errors import NotFoundError, ConflictError
from config import settings

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    """Repository for user operations"""
    
    def __init__(self, db: AsyncDatabase):
        super().__init__(User, db)
    
    @track_db_query("user-service", "get_by_email", "users")
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        async with self.db.session() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            return result.scalars().first()
    
    @track_db_query("user-service", "get_by_username", "users")
    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        async with self.db.session() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            return result.scalars().first()
    
    @track_db_query("user-service", "search_users", "users")
    async def search_users(
        self, 
        search: Optional[str] = None, 
        skip: int = 0, 
        limit: int = 100
    ) -> Dict[str, Any]:
        """Search users with pagination"""
        async with self.db.session() as session:
            # Build query
            query = select(User)
            
            # Add search filter if provided
            if search:
                query = query.where(
                    or_(
                        User.username.ilike(f"%{search}%"),
                        User.email.ilike(f"%{search}%")
                    )
                )
            
            # Count total users for pagination
            count_query = select(func.count()).select_from(query.subquery())
            total = await session.scalar(count_query) or 0
            
            # Get paginated results
            query = query.order_by(User.id).offset(skip).limit(limit)
            result = await session.execute(query)
            users = result.scalars().all()
            
            # Calculate pages
            pages = (total + limit - 1) // limit if limit > 0 else 1
            
            return {
                "items": users,
                "total": total,
                "page": (skip // limit) + 1 if limit > 0 else 1,
                "size": limit,
                "pages": pages
            }
    
    @track_db_query("user-service", "update_progression", "users")
    async def update_progression(
        self, user_id: int, level: Optional[int] = None, experience: Optional[int] = None
    ) -> Optional[User]:
        """Update user progression"""
        async with self.db.session() as session:
            # Check if user exists
            user = await session.get(User, user_id)
            if not user:
                return None
            
            # Update fields
            if level is not None:
                user.level = level
            
            if experience is not None:
                user.experience = experience
            
            # Save changes
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
            return user


class TokenRepository:
    """Repository for token operations"""
    
    def __init__(self, db: AsyncDatabase):
        self.db = db
    
    @track_db_query("user-service", "create_token", "tokens")
    async def create_token(
        self, 
        user_id: int, 
        token: str, 
        token_type: TokenType, 
        expires_at: datetime
    ) -> Token:
        """Create a new token"""
        async with self.db.session() as session:
            # Create token
            new_token = Token(
                user_id=user_id,
                token=token,
                token_type=token_type,
                expires_at=expires_at
            )
            
            # Save to database
            session.add(new_token)
            await session.commit()
            await session.refresh(new_token)
            
            return new_token
    
    @track_db_query("user-service", "get_token", "tokens")
    async def get_token(
        self, token: str, token_type: TokenType | None = None
    ) -> Optional[Token]:
        """Get a token by its value and optionally token type"""
        async with self.db.session() as session:
            # Build query
            query = select(Token).where(Token.token == token)
            
            # Add token type filter if provided
            if token_type:
                query = query.where(Token.token_type == token_type)
            
            # Execute query
            result = await session.execute(query)
            return result.scalars().first()
    
    @track_db_query("user-service", "invalidate_token", "tokens")
    async def invalidate_token(self, token: str) -> bool:
        """Invalidate a token"""
        async with self.db.session() as session:
            # Find token
            token_obj = await self.get_token(token)
            if not token_obj:
                return False
            
            # Mark as revoked
            token_obj.is_revoked = True
            session.add(token_obj)
            await session.commit()
            
            return True
    
    @track_db_query("user-service", "invalidate_user_tokens", "tokens")
    async def invalidate_user_tokens(
        self, user_id: int, token_type: Optional[TokenType] = None
    ) -> int:
        """Invalidate all tokens for a user"""
        async with self.db.session() as session:
            # Build query
            query = (
                update(Token)
                .where(Token.user_id == user_id)
                .where(Token.is_revoked == False)
                .values(is_revoked=True)
            )
            
            # Add token type filter if provided
            if token_type:
                query = query.where(Token.token_type == token_type)
            
            # Execute query
            result = await session.execute(query)
            await session.commit()
            
            return result.rowcount
    
    @track_db_query("user-service", "cleanup_expired_tokens", "tokens")
    async def cleanup_expired_tokens(self) -> int:
        """Remove expired tokens from the database"""
        async with self.db.session() as session:
            # Delete expired tokens
            query = (
                delete(Token)
                .where(Token.expires_at < datetime.utcnow())
            )
            
            # Execute query
            result = await session.execute(query)
            await session.commit()
            
            return result.rowcount