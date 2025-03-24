import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import uuid

from common.auth import verify_password, get_password_hash, JWTHandler
from common.database import AsyncDatabase
from common.cache import CacheClient
from common.messaging import RabbitMQConnection
from common.errors import NotFoundError, AuthenticationError, ValidationError, ConflictError
from common.tracing import trace_function

from models import User, Token, TokenType, UserRole
from repository import UserRepository, TokenRepository
from schemas import UserCreate, UserUpdate, UserInDB, UserResponse, UserList, UserProgressionUpdate
from config import settings

logger = logging.getLogger(__name__)


class UserService:
    """Service for user operations"""
    
    def __init__(
        self,
        db: AsyncDatabase,
        cache: CacheClient,
        message_broker: RabbitMQConnection
    ):
        self.db = db
        self.cache = cache
        self.message_broker = message_broker
        self.user_repository = UserRepository(db)
        self.token_repository = TokenRepository(db)
        self.jwt_handler = JWTHandler(
            settings.JWT_SECRET,
            settings.JWT_ALGORITHM,
            settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            settings.REFRESH_TOKEN_EXPIRE_MINUTES
        )
    
    @trace_function("create_user", service_name="user-service")
    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user"""
        # Check if email or username is already taken
        existing_email = await self.user_repository.get_by_email(user_data.email)
        if existing_email:
            raise ConflictError(f"User with email {user_data.email} already exists")
        
        existing_username = await self.user_repository.get_by_username(user_data.username)
        if existing_username:
            raise ConflictError(f"User with username {user_data.username} already exists")
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Create user
        user = await self.user_repository.create({
            "email": user_data.email,
            "username": user_data.username,
            "hashed_password": hashed_password,
            "role": UserRole.USER,
            "level": 1,
            "experience": 0,
            "is_active": True
        })
        
        # Publish user created event
        await self.message_broker.publish_event(
            "user_created",
            {"user_id": user.id, "email": user.email, "username": user.username},
            f"event.user.created"
        )
        
        # Cache user
        await self.cache_user(user)
        
        return user
    
    @trace_function("get_user", service_name="user-service")
    async def get_user(self, user_id: int) -> User:
        """Get a user by ID"""
        # Try to get from cache first
        cached_user = await self.get_cached_user(user_id)
        if cached_user:
            return cached_user
        
        # Get from database
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")
        
        # Cache for future requests
        await self.cache_user(user)
        
        return user
    
    @trace_function("get_user_by_email", service_name="user-service")
    async def get_user_by_email(self, email: str) -> User:
        """Get a user by email"""
        # Get from database
        user = await self.user_repository.get_by_email(email)
        if not user:
            raise NotFoundError(f"User with email {email} not found")
        
        return user
    
    @trace_function("update_user", service_name="user-service")
    async def update_user(self, user_id: int, user_data: UserUpdate) -> User:
        """Update user information"""
        # Get user
        user = await self.get_user(user_id)
        
        # Check if email is being updated and if it's already taken
        if user_data.email and user_data.email != user.email:
            existing_email = await self.user_repository.get_by_email(user_data.email)
            if existing_email:
                raise ConflictError(f"User with email {user_data.email} already exists")
        
        # Check if username is being updated and if it's already taken
        if user_data.username and user_data.username != user.username:
            existing_username = await self.user_repository.get_by_username(user_data.username)
            if existing_username:
                raise ConflictError(f"User with username {user_data.username} already exists")
        
        # Update user
        update_data = user_data.dict(exclude_unset=True)
        user = await self.user_repository.update(user_id, update_data)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")
        
        # Invalidate cache
        await self.invalidate_user_cache(user_id)
        
        # Publish user updated event
        await self.message_broker.publish_event(
            "user_updated",
            {"user_id": user.id, "email": user.email, "username": user.username},
            f"event.user.updated"
        )
        
        return user
    
    @trace_function("delete_user", service_name="user-service")
    async def delete_user(self, user_id: int) -> bool:
        """Delete a user"""
        # Get user
        user = await self.get_user(user_id)
        
        # Delete user
        success = await self.user_repository.delete(user_id)
        if not success:
            return False
        
        # Invalidate cache
        await self.invalidate_user_cache(user_id)
        
        # Publish user deleted event
        await self.message_broker.publish_event(
            "user_deleted",
            {"user_id": user_id},
            f"event.user.deleted"
        )
        
        # Invalidate all tokens
        await self.token_repository.invalidate_user_tokens(user_id)
        
        return True
    
    @trace_function("authenticate_user", service_name="user-service")
    async def authenticate_user(self, email: str, password: str) -> Tuple[User, str, str]:
        """Authenticate a user and generate tokens"""
        # Get user
        try:
            user = await self.get_user_by_email(email)
        except NotFoundError:
            raise AuthenticationError("Invalid email or password")
        
        # Check if user is active
        if not user.is_active:
            raise AuthenticationError("User is inactive")
        
        # Verify password
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")
        
        # Generate tokens
        access_token = self.jwt_handler.create_access_token(
            user.id,
            data={"email": user.email, "role": user.role}
        )
        
        refresh_token = self.jwt_handler.create_refresh_token(user.id)
        
        # Save refresh token
        expires_at = datetime.utcnow() + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        await self.token_repository.create_token(
            user.id,
            refresh_token,
            TokenType.REFRESH,
            expires_at
        )
        
        return user, access_token, refresh_token
    
    @trace_function("refresh_token", service_name="user-service")
    async def refresh_token(self, refresh_token: str) -> Tuple[str, str]:
        """Refresh access token using refresh token"""
        # Get token
        token = await self.token_repository.get_token(refresh_token, TokenType.REFRESH)
        if not token:
            raise AuthenticationError("Invalid refresh token")
        
        # Check if token is expired or revoked
        if token.expires_at < datetime.utcnow() or token.is_revoked:
            raise AuthenticationError("Token expired or revoked")
        
        # Get user
        user = await self.get_user(token.user_id)
        
        # Generate new access token
        access_token = self.jwt_handler.create_access_token(
            user.id,
            data={"email": user.email, "role": user.role}
        )
        
        # Generate new refresh token
        new_refresh_token = self.jwt_handler.create_refresh_token(user.id)
        
        # Save new refresh token
        expires_at = datetime.utcnow() + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        await self.token_repository.create_token(
            user.id,
            new_refresh_token,
            TokenType.REFRESH,
            expires_at
        )
        
        # Invalidate old refresh token
        await self.token_repository.invalidate_token(refresh_token)
        
        return access_token, new_refresh_token
    
    @trace_function("logout", service_name="user-service")
    async def logout(self, refresh_token: str) -> bool:
        """Logout a user by invalidating refresh token"""
        return await self.token_repository.invalidate_token(refresh_token)
    
    @trace_function("change_password", service_name="user-service")
    async def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> bool:
        """Change user password"""
        # Get user
        user = await self.get_user(user_id)
        
        # Verify current password
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        
        # Update password
        hashed_password = get_password_hash(new_password)
        await self.user_repository.update(user_id, {"hashed_password": hashed_password})
        
        # Invalidate all refresh tokens
        await self.token_repository.invalidate_user_tokens(user_id, TokenType.REFRESH)
        
        # Publish password changed event
        await self.message_broker.publish_event(
            "user_password_changed",
            {"user_id": user_id},
            f"event.user.password_changed"
        )
        
        return True
    
    @trace_function("request_password_reset", service_name="user-service")
    async def request_password_reset(self, email: str) -> str:
        """Request password reset and return token"""
        # Get user
        try:
            user = await self.get_user_by_email(email)
        except NotFoundError:
            # For security reasons, don't reveal if email exists
            return ""
        
        # Generate token
        reset_token = str(uuid.uuid4())
        
        # Save token
        expires_at = datetime.utcnow() + timedelta(hours=24)
        await self.token_repository.create_token(
            user.id,
            reset_token,
            TokenType.RESET_PASSWORD,
            expires_at
        )
        
        # Publish password reset requested event
        await self.message_broker.publish_event(
            "user_password_reset_requested",
            {"user_id": user.id, "email": user.email, "token": reset_token},
            f"event.user.password_reset_requested"
        )
        
        return reset_token
    
    @trace_function("reset_password", service_name="user-service")
    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password using token"""
        # Get token
        token_obj = await self.token_repository.get_token(token, TokenType.RESET_PASSWORD)
        if not token_obj:
            raise AuthenticationError("Invalid reset token")
        
        # Check if token is expired or revoked
        if token_obj.expires_at < datetime.utcnow() or token_obj.is_revoked:
            raise AuthenticationError("Token expired or revoked")
        
        # Update password
        hashed_password = get_password_hash(new_password)
        await self.user_repository.update(token_obj.user_id, {"hashed_password": hashed_password})
        
        # Invalidate token
        await self.token_repository.invalidate_token(token)
        
        # Invalidate all refresh tokens
        await self.token_repository.invalidate_user_tokens(token_obj.user_id, TokenType.REFRESH)
        
        # Publish password reset event
        await self.message_broker.publish_event(
            "user_password_reset",
            {"user_id": token_obj.user_id},
            f"event.user.password_reset"
        )
        
        return True
    
    @trace_function("update_progression", service_name="user-service")
    async def update_progression(
        self, user_id: int, progression_data: UserProgressionUpdate
    ) -> User:
        """Update user progression"""
        # Get user
        user = await self.get_user(user_id)
        
        # Update progression
        level = progression_data.level
        experience = progression_data.experience
        
        if level is None and experience is None:
            return user
        
        user = await self.user_repository.update_progression(user_id, level, experience)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")
        
        # Invalidate cache
        await self.invalidate_user_cache(user_id)
        
        # Publish progression updated event
        event_data = {"user_id": user_id}
        if level is not None:
            event_data["level"] = level
        if experience is not None:
            event_data["experience"] = experience
        
        await self.message_broker.publish_event(
            "user_progression_updated",
            event_data,
            f"event.user.progression_updated"
        )
        
        return user
    
    @trace_function("get_users", service_name="user-service")
    async def get_users(
        self, search: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> UserList:
        """Get a list of users with pagination"""
        result = await self.user_repository.search_users(search, skip, limit)
        return UserList(**result)
    
    @trace_function("cache_user", service_name="user-service")
    async def cache_user(self, user: User) -> None:
        """Cache user data"""
        await self.cache.set_json(
            f"user:{user.id}",
            {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "level": user.level,
                "experience": user.experience,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
                "hashed_password": user.hashed_password
            },
            expire=3600  # 1 hour
        )
    
    @trace_function("get_cached_user", service_name="user-service")
    async def get_cached_user(self, user_id: int) -> Optional[User]:
        """Get user from cache"""
        user_data = await self.cache.get_json(f"user:{user_id}")
        if not user_data:
            return None
        
        # Convert back to User model
        user = User(
            id=user_data["id"],
            email=user_data["email"],
            username=user_data["username"],
            role=user_data["role"],
            level=user_data["level"],
            experience=user_data["experience"],
            is_active=user_data["is_active"],
            hashed_password=user_data["hashed_password"]
        )
        
        # Parse dates
        if user_data.get("created_at"):
            user.created_at = datetime.fromisoformat(user_data["created_at"])
        
        if user_data.get("updated_at"):
            user.updated_at = datetime.fromisoformat(user_data["updated_at"])
        
        return user
    
    @trace_function("invalidate_user_cache", service_name="user-service")
    async def invalidate_user_cache(self, user_id: int) -> None:
        """Invalidate user cache"""
        try:
            cache_key = f"user:{user_id}"
            await self.cache.delete(cache_key)
            logger.info(f"User cache invalidated for user {user_id}")
        except Exception as e:
            logger.error(f"Error invalidating user cache: {str(e)}")

    @trace_function("handle_achievement_unlocked", service_name="user-service")
    async def handle_achievement_unlocked(self, event_data: dict) -> None:
        """Handle achievement.unlocked event"""
        try:
            # Extract data from event
            user_id = event_data.get("user_id")
            achievement_points = event_data.get("points", 0)
            
            if not user_id:
                logger.warning("Received achievement.unlocked event without user_id")
                return
                
            # Update user experience points
            user = await self.get_user(user_id)
            
            # Add achievement points to user's experience
            progression_data = {
                "experience": user.experience + achievement_points
            }
            
            # Update progression
            await self.update_progression(user_id, UserProgressionUpdate(**progression_data))
            
            logger.info(f"Updated user {user_id} progression after achievement unlock. Added {achievement_points} points")
        except NotFoundError:
            logger.warning(f"Received achievement.unlocked event for non-existent user {user_id}")
        except Exception as e:
            logger.error(f"Error handling achievement.unlocked event: {str(e)}")