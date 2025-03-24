import os
from typing import List, Optional, Dict

from pydantic import BaseModel, PostgresDsn
from pydantic_settings import BaseSettings
from common.rate_limit import RateLimitConfig, RateLimitStrategy


class UserServiceSettings(BaseSettings):
    """Configuration for User Service"""
    # Service information
    SERVICE_NAME: str = "user-service"
    SERVICE_VERSION: str = "0.1.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    
    # JWT settings
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "changethissecretkey")
    JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    REFRESH_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("REFRESH_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days
    
    # CORS settings
    CORS_ORIGINS: List[str] = os.environ.get("CORS_ORIGINS", "*").split(",")
    
    # Database settings
    DB_HOST: str = os.environ.get("DB_HOST", "localhost")
    DB_PORT: int = int(os.environ.get("DB_PORT", "5432"))
    DB_USER: str = os.environ.get("DB_USER", "postgres")
    DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "postgres")
    DB_NAME: str = os.environ.get("DB_NAME", "user_service")
    
    # RabbitMQ settings
    RABBITMQ_HOST: str = os.environ.get("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT: int = int(os.environ.get("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER: str = os.environ.get("RABBITMQ_USER", "guest")
    RABBITMQ_PASS: str = os.environ.get("RABBITMQ_PASS", "guest")
    
    # Redis settings
    REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.environ.get("REDIS_PASSWORD", "redispassword")
    # Logging
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    
    # API versioning
    API_VERSION_PREFIX: str = "v"
    DEFAULT_API_VERSION: str = "1"
    SUPPORTED_API_VERSIONS: List[str] = ["1"]
    DEPRECATED_API_VERSIONS: List[str] = []
    
    # Rate limiting configuration
    ENABLE_RATE_LIMITING: bool = True
    RATE_LIMIT: int = 100  # requests per window
    RATE_LIMIT_WINDOW: int = 60  # seconds
    RATE_LIMIT_STRATEGY: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    RATE_LIMIT_EXCLUDED_PATHS: List[str] = ["/health", "/metrics", "/api/versions", "/api/rate-limit"]
    
    # Endpoint-specific rate limits
    RATE_LIMIT_ENDPOINT_CONFIGS: Dict[str, RateLimitConfig] = {
        "/auth/token": RateLimitConfig(limit=10, window=60),  # Limit login attempts
        "/auth/refresh": RateLimitConfig(limit=20, window=60),  # Limit token refreshes
        "/password-reset": RateLimitConfig(limit=5, window=300),  # Limit password reset requests
        "/password-reset/confirm": RateLimitConfig(limit=5, window=300),  # Limit password reset confirmations
    }
    
    @property
    def DATABASE_URL(self) -> str:
        """Get PostgreSQL async URL"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Get PostgreSQL sync URL for Alembic"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


# Create settings instance
settings = UserServiceSettings()