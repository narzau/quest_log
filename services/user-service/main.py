import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from common.service import create_microservice, VersionedAPIRouter
from common.database import AsyncDatabase
from common.errors import register_error_handlers
from common.health import HealthCheck, check_postgres, check_redis, check_rabbitmq

from config import settings
from service import UserService
from models import User
from repository import UserRepository, TokenRepository
from cqrs import (
    # Commands
    CreateUserCommand, UpdateUserCommand, DeleteUserCommand,
    UpdateProgressionCommand, ChangePasswordCommand,
    ResetPasswordCommand, RequestPasswordResetCommand,
    # Queries
    GetUserQuery, GetUserByEmailQuery, GetUserByUsernameQuery,
    GetUsersQuery, AuthenticateUserQuery, RefreshTokenQuery,
    # Events
    UserCreatedEvent, UserUpdatedEvent, UserDeletedEvent,
    UserProgressionUpdatedEvent, UserLoggedInEvent, UserLoggedOutEvent,
    PasswordChangedEvent, PasswordResetRequestedEvent, PasswordResetEvent
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Log the DATABASE_URL before creating the connection
logger.info(f"About to connect to DATABASE_URL: {settings.DATABASE_URL}")
logger.info(f"DB_HOST value: {settings.DB_HOST}")

# Create database connection
db = AsyncDatabase(settings.DATABASE_URL)
logger.info(f"DATABASE_URL after connection: {settings.DATABASE_URL}")
user_repository = UserRepository(db)
token_repository = TokenRepository(db)

# Create global service instance
user_service = None

# Create versioned router
router = VersionedAPIRouter(
    version=["1"],  # Current version
    tags=[settings.SERVICE_NAME],
)

# Define lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application"""
    global user_service
    
    # Create cache client and message broker directly (don't use from service)
    from common.cache import get_cache_client
    from common.messaging import get_rabbitmq_connection
    
    # Get Redis password from environment
    logger.info(f"Connecting to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    
    cache_client = await get_cache_client(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        prefix=f"{settings.SERVICE_NAME}:",
        password=settings.REDIS_PASSWORD
    )
    
    # Get RabbitMQ credentials from environment
    rabbitmq_user = os.environ.get("RABBITMQ_USER", "guest")
    rabbitmq_password = os.environ.get("RABBITMQ_PASSWORD", "guest")
    
    rabbit_connection = await get_rabbitmq_connection(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        user=rabbitmq_user,
        password=rabbitmq_password,
        service_name=settings.SERVICE_NAME
    )
    
    # Initialize user service with our dependencies
    user_service = UserService(
        db=db,
        cache=cache_client,
        message_broker=rabbit_connection
    )
    
    # Try to create tables if they don't exist
    try:
        await db.create_tables()
        logger.info("Database tables created or already exist")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
    
    # Set up health check for service-specific dependencies
    health_check = HealthCheck(settings.SERVICE_NAME, settings.SERVICE_VERSION)
    
    # Add dependency checks
    health_check.add_dependency_check(
        "database", 
        lambda: check_postgres(settings.DATABASE_URL)
    )
    
    health_check.add_dependency_check(
        "redis", 
        lambda: check_redis(settings.REDIS_HOST, settings.REDIS_PORT)
    )
    
    health_check.add_dependency_check(
        "rabbitmq",
        lambda: check_rabbitmq(
            settings.RABBITMQ_HOST, 
            settings.RABBITMQ_PORT, 
            settings.RABBITMQ_USER, 
            settings.RABBITMQ_PASS
        )
    )
    
    # Register event handlers for the service
    await rabbit_connection.subscribe_to_events([
        "achievement.unlocked"
    ])

    # Register event handler for achievement.unlocked
    rabbit_connection.subscribe_event(
        "achievement.unlocked", 
        user_service.handle_achievement_unlocked
    )
    
    # Register CQRS handlers
    # Command handlers
    service.register_command_handler(CreateUserCommand, user_service.create_user)
    service.register_command_handler(UpdateUserCommand, user_service.update_user)
    service.register_command_handler(DeleteUserCommand, user_service.delete_user)
    service.register_command_handler(UpdateProgressionCommand, user_service.update_progression)
    service.register_command_handler(ChangePasswordCommand, user_service.change_password)
    service.register_command_handler(ResetPasswordCommand, user_service.reset_password)
    service.register_command_handler(RequestPasswordResetCommand, user_service.request_password_reset)

    # Query handlers
    service.register_query_handler(GetUserQuery, user_service.get_user)
    service.register_query_handler(GetUserByEmailQuery, user_service.get_user_by_email)
    service.register_query_handler(GetUsersQuery, user_service.get_users)
    service.register_query_handler(AuthenticateUserQuery, user_service.authenticate_user)
    service.register_query_handler(RefreshTokenQuery, user_service.refresh_token)

    # Event handlers - for future use with other services
    service.register_event_handler(UserCreatedEvent, lambda e: logger.info(f"User created: {e.user_id}"))
    service.register_event_handler(UserDeletedEvent, lambda e: logger.info(f"User deleted: {e.user_id}"))
    service.register_event_handler(UserLoggedInEvent, lambda e: logger.info(f"User logged in: {e.user_id}"))

    # Import routes and set up routes after user_service is initialized
    from routes import setup_routes
    setup_routes(router, get_user_service)
    
    # Include router with versioning support
    service.include_router(router, prefix="")
    
    logger.info(f"{settings.SERVICE_NAME} fully initialized")
    
    yield  # This is where the application runs
    
    # Cleanup code when the application is shutting down
    logger.info(f"{settings.SERVICE_NAME} shutting down")
    
    # Clean up resources
    await cache_client.close()
    await rabbit_connection.close()

# Create the microservice
service = create_microservice(
    service_name=settings.SERVICE_NAME,
    port=settings.PORT,
    event_subscriptions=[
        "user.#",  # All user-related events
        "achievement.unlocked",  # For updating user progression
    ],
    db_connection_string=settings.DATABASE_URL,
    jwt_secret=settings.JWT_SECRET,
    supported_api_versions=settings.SUPPORTED_API_VERSIONS,
    default_api_version=settings.DEFAULT_API_VERSION,
    deprecated_api_versions=settings.DEPRECATED_API_VERSIONS,
    lifespan=lifespan,  # Pass the lifespan directly to create_microservice
)

# Configure rate limiting from settings
service.config.enable_rate_limiting = settings.ENABLE_RATE_LIMITING
service.config.rate_limit = settings.RATE_LIMIT
service.config.rate_limit_window = settings.RATE_LIMIT_WINDOW
service.config.rate_limit_strategy = settings.RATE_LIMIT_STRATEGY
service.config.rate_limit_excluded_paths = settings.RATE_LIMIT_EXCLUDED_PATHS
service.config.rate_limit_endpoint_configs = settings.RATE_LIMIT_ENDPOINT_CONFIGS

# Dependency for user service
def get_user_service() -> UserService:
    """Get user service instance"""
    if not user_service:
        raise RuntimeError("User service not initialized")
    return user_service

# Register error handlers
register_error_handlers(service.app)

# Add API examples to documentation
service.doc.add_tag_description(
    "users",
    "User operations including authentication, profile management, and user data"
)

service.doc.add_tag_description(
    "authentication",
    "Authentication operations including login, token refresh, and logout"
)

service.doc.add_tag_description(
    "admin",
    "Administrative operations for managing users (requires admin role)"
)

# Add examples
from common.documentation import ApiExample

# Authentication example
service.doc.add_example(
    path="/auth/token",
    method="post",
    content_type="application/json",
    example=ApiExample(
        summary="Login successful",
        description="Example of a successful login response",
        request_example={
            "username": "user@example.com",
            "password": "password123"
        },
        response_example={
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer",
            "user": {
                "id": 1,
                "email": "user@example.com",
                "username": "john_doe",
                "role": "USER",
                "is_active": True,
                "level": 1,
                "experience_points": 0
            }
        }
    )
)

# User creation example
service.doc.add_example(
    path="/",
    method="post",
    content_type="application/json",
    example=ApiExample(
        summary="Create user",
        description="Example of creating a new user",
        request_example={
            "email": "newuser@example.com",
            "username": "newuser",
            "password": "password123"
        },
        response_example={
            "id": 2,
            "email": "newuser@example.com",
            "username": "newuser",
            "role": "USER",
            "is_active": True,
            "level": 1,
            "experience": 0,
            "created_at": "2023-06-15T10:30:45Z",
            "updated_at": "2023-06-15T10:30:45Z"
        }
    )
)

# User profile example
service.doc.add_example(
    path="/me",
    method="get",
    content_type="application/json",
    example=ApiExample(
        summary="Get user profile",
        description="Example of retrieving the current user's profile",
        response_example={
            "id": 1,
            "email": "user@example.com",
            "username": "john_doe",
            "role": "USER",
            "is_active": True,
            "level": 5,
            "experience": 1250,
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": "2023-06-10T15:20:30Z"
        }
    )
)

if __name__ == "__main__":
    service.run()