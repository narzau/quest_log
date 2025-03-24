import os
from typing import List, Optional

from pydantic import BaseModel


class ServiceConfig(BaseModel):
    """Configuration for a backend service"""
    name: str
    url: str
    prefix: str


class ApiGatewayConfig(BaseModel):
    """Configuration for API Gateway"""
    jwt_secret: str = os.environ.get("JWT_SECRET", "changethissecretkey")
    jwt_algorithm: str = os.environ.get("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    cors_origins: List[str] = os.environ.get("CORS_ORIGINS", "*").split(",")
    
    # RabbitMQ configuration
    rabbitmq_host: str = os.environ.get("RABBITMQ_HOST", "localhost")
    rabbitmq_port: int = int(os.environ.get("RABBITMQ_PORT", "5672"))
    rabbitmq_user: str = os.environ.get("RABBITMQ_USER", "guest")
    rabbitmq_pass: str = os.environ.get("RABBITMQ_PASS", "guest")
    
    # Redis configuration
    redis_host: str = os.environ.get("REDIS_HOST", "localhost")
    redis_port: int = int(os.environ.get("REDIS_PORT", "6379"))
    
    # Service name
    service_name: str = os.environ.get("API_GATEWAY_SERVICE_NAME", "api-gateway")
    
    # Services configuration
    services: List[ServiceConfig] = [
        ServiceConfig(
            name="user", 
            url=os.environ.get("USER_SERVICE_URL", "http://user-service:8001"),
            prefix="/api/v1/users"
        ),
        ServiceConfig(
            name="quest", 
            url=os.environ.get("QUEST_SERVICE_URL", "http://quest-service:8002"),
            prefix="/api/v1/quests"
        ),
        ServiceConfig(
            name="note", 
            url=os.environ.get("NOTE_SERVICE_URL", "http://note-service:8003"),
            prefix="/api/v1/notes"
        ),
        ServiceConfig(
            name="voice", 
            url=os.environ.get("VOICE_SERVICE_URL", "http://voice-service:8004"),
            prefix="/api/v1/voice"
        ),
        ServiceConfig(
            name="subscription", 
            url=os.environ.get("SUBSCRIPTION_SERVICE_URL", "http://subscription-service:8005"),
            prefix="/api/v1/subscription"
        ),
        ServiceConfig(
            name="integration", 
            url=os.environ.get("INTEGRATION_SERVICE_URL", "http://integration-service:8006"),
            prefix="/api/v1/integrations"
        ),
    ]


# Create config instance
config = ApiGatewayConfig()