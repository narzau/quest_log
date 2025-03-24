import logging
import os
import re
from typing import Optional, Dict, Any, List, Callable, Union, Tuple, AsyncContextManager
from enum import Enum
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import Route
from starlette.types import Lifespan  # Import the correct Lifespan type

from common.messaging import get_rabbitmq_connection, RabbitMQConnection
from common.cache import get_cache_client, CacheClient
# Import monitoring with optional tracing
try:
    from common.monitoring import setup_monitoring
except ImportError as e:
    # Define a fallback function if monitoring setup fails
    def setup_monitoring(app: FastAPI, service_name: str) -> None:
        logger.warning(f"Monitoring setup skipped due to import error: {e}")
        
        @app.get("/metrics")
        async def metrics():
            return {"message": "Metrics endpoint disabled due to missing dependencies"}
from common.auth import JWTHandler
from common.documentation import setup_documentation, APIDocumentation, ApiExample
from common.rate_limit import setup_rate_limiting, RateLimitStrategy, RateLimitConfig
from common.cqrs import CQRSRegistry

logger = logging.getLogger(__name__)


class VersionedAPIRouter(APIRouter):
    """Router that supports API versioning"""
    
    def __init__(
        self,
        *args,
        version: Union[str, List[str]] = "1",
        deprecated_versions: List[str] = [],
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        
        # Convert single version to list for consistency
        if isinstance(version, str):
            version = [version]
            
        self.versions = version
        self.deprecated_versions = deprecated_versions or []


class MicroserviceConfig:
    """Configuration for microservice"""
    service_name: str
    service_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8000
    rabbitmq_host: str = os.getenv("RABBITMQ_HOST", "localhost")
    rabbitmq_port: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_user: str = os.getenv("RABBITMQ_USER", "guest")
    rabbitmq_pass: str = os.getenv("RABBITMQ_PASS", "guest")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    cors_origins: List[str] = ["*"]
    db_connection_string: Optional[str] = None
    jwt_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    log_level: str = "INFO"
    event_subscriptions: List[str] = []
    
    # API versioning configuration
    api_version_prefix: str = "v"  # Prefix for version in URL (e.g., /v1/users)
    default_api_version: str = "1"  # Default API version
    supported_api_versions: List[str] = ["1"]  # Supported API versions
    deprecated_api_versions: List[str] = []  # Deprecated but still supported versions
    
    # Rate limiting configuration
    enable_rate_limiting: bool = True
    rate_limit: int = 100  # requests per window
    rate_limit_window: int = 60  # seconds
    rate_limit_strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    rate_limit_endpoint_configs: Dict[str, RateLimitConfig] = {}
    rate_limit_excluded_paths: List[str] = ["/health", "/metrics"]


class BaseMicroservice:
    """Base class for microservices"""
    
    def __init__(self, config: MicroserviceConfig, lifespan: Optional[Lifespan[FastAPI]] = None):
        self.config = config
        
        # Create FastAPI app with versioning information in description
        versions_text = ", ".join(f"{config.api_version_prefix}{v}" for v in config.supported_api_versions)
        deprecated_text = ""
        if config.deprecated_api_versions:
            deprecated_versions = ", ".join(f"{config.api_version_prefix}{v}" for v in config.deprecated_api_versions)
            deprecated_text = f"\n\nDeprecated versions: {deprecated_versions}"
            
        rate_limit_text = ""
        if config.enable_rate_limiting:
            rate_limit_text = f"\n\nAPI Rate Limit: {config.rate_limit} requests per {config.rate_limit_window} seconds"
            
        self.app = FastAPI(
            title=f"{config.service_name.capitalize()} Service",
            description=f"API for {config.service_name} service. Supported versions: {versions_text}{deprecated_text}{rate_limit_text}",
            version=config.service_version,
            lifespan=lifespan,  # Use the lifespan context manager if provided
        )
        
        # Set up enhanced documentation
        self.doc = setup_documentation(
            app=self.app,
            title=f"{config.service_name.capitalize()} Service",
            description=f"API for {config.service_name} service. Supported versions: {versions_text}{deprecated_text}{rate_limit_text}",
            version=config.service_version,
            contact={"name": "DevOps Team", "email": "devops@questlogger.com"},
            license_info={"name": "MIT License", "url": "https://opensource.org/licenses/MIT"},
        )
        
        # Initialize CQRS registry (will be populated in startup)
        self.cqrs = None
        
        # Add standard tag descriptions
        self.doc.add_tag_description(
            config.service_name,
            f"Core operations for the {config.service_name} service"
        )
        
        # Add descriptions for version tags
        for version in config.supported_api_versions:
            self.doc.add_tag_description(
                f"v{version}",
                f"API Version {version} endpoints" + (
                    " (Current stable version)" if version == config.default_api_version else ""
                )
            )
        
        # Add descriptions for deprecated version tags
        for version in config.deprecated_api_versions:
            self.doc.add_tag_description(
                f"v{version}",
                f"API Version {version} endpoints (DEPRECATED - will be removed in future versions)"
            )
        
        # Set up CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Set up rate limiting if enabled
        if config.enable_rate_limiting:
            setup_rate_limiting(
                app=self.app,
                redis_host=config.redis_host,
                redis_port=config.redis_port,
                redis_prefix=f"ratelimit:{config.service_name}:",
                default_limit=config.rate_limit,
                default_window=config.rate_limit_window,
                strategy=config.rate_limit_strategy,
                endpoint_configs=config.rate_limit_endpoint_configs,
                excluded_paths=config.rate_limit_excluded_paths,
            )
        
        # Set up monitoring
        setup_monitoring(self.app, config.service_name)
        
        # Set up logging
        logging.basicConfig(
            level=getattr(logging, config.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        
        # JWT handler if authentication is needed
        self.jwt_handler = None
        if config.jwt_secret:
            self.jwt_handler = JWTHandler(
                config.jwt_secret,
                config.jwt_algorithm,
                config.access_token_expire_minutes,
            )
        
        # Health check endpoint
        @self.app.get("/health", tags=["Health"], summary="Service Health Check", 
                      description="Verify the service is running and responding to requests")
        async def health_check():
            return {"status": "ok", "service": config.service_name}
        
        # API Version information endpoint
        @self.app.get("/api/versions", tags=["API"], summary="Get API Versions",
                      description="Returns information about supported API versions and identifies deprecated versions")
        async def api_versions():
            return {
                "current": config.default_api_version,
                "supported": config.supported_api_versions,
                "deprecated": config.deprecated_api_versions
            }
            
        # Rate limiting information endpoint
        @self.app.get("/api/rate-limit", tags=["API"], summary="Get Rate Limit Info",
                     description="Returns information about the current rate limiting configuration")
        async def rate_limit_info():
            if not config.enable_rate_limiting:
                return {"enabled": False}
                
            return {
                "enabled": True,
                "limit": config.rate_limit,
                "window_seconds": config.rate_limit_window,
                "strategy": config.rate_limit_strategy,
                "excluded_paths": config.rate_limit_excluded_paths
            }
        
        # Startup and shutdown events
        @self.app.on_event("startup")
        async def startup_event():
            await self.startup()
        
        @self.app.on_event("shutdown")
        async def shutdown_event():
            await self.shutdown()
            
        # Add documentation examples
        self.doc.add_example(
            path="/health",
            method="get",
            content_type="default",
            example=ApiExample(
                response_example={"status": "ok", "service": config.service_name},
                summary="Successful health check",
                description="Example response for a healthy service instance"
            )
        )
        
        self.doc.add_example(
            path="/api/versions",
            method="get",
            content_type="default",
            example=ApiExample(
                response_example={
                    "current": config.default_api_version,
                    "supported": config.supported_api_versions,
                    "deprecated": config.deprecated_api_versions
                },
                summary="API version information",
                description="Shows currently supported and deprecated API versions"
            )
        )
        
        self.doc.add_example(
            path="/api/rate-limit",
            method="get",
            content_type="default",
            example=ApiExample(
                response_example={
                    "enabled": True,
                    "limit": config.rate_limit,
                    "window_seconds": config.rate_limit_window,
                    "strategy": config.rate_limit_strategy,
                    "excluded_paths": config.rate_limit_excluded_paths
                },
                summary="Rate limit configuration",
                description="Shows the current rate limiting settings"
            )
        )
    
    async def startup(self):
        """Startup hook for the service"""
        # Connect to RabbitMQ
        self.rabbit_connection = await get_rabbitmq_connection(
            host=self.config.rabbitmq_host,
            port=self.config.rabbitmq_port,
            user=self.config.rabbitmq_user,
            password=self.config.rabbitmq_pass,
            service_name=self.config.service_name
        )
        
        # Connect to Redis
        self.cache_client = await get_cache_client(
            host=self.config.redis_host,
            port=self.config.redis_port,
            prefix=f"{self.config.service_name}:"
        )
        
        # Initialize CQRS registry with RabbitMQ connection
        self.cqrs = CQRSRegistry(self.rabbit_connection)
        
        # Subscribe to events
        if self.config.event_subscriptions:
            await self.rabbit_connection.subscribe_to_events(
                self.config.event_subscriptions
            )
        
        logger.info(f"{self.config.service_name} service started")
    
    async def shutdown(self):
        """Shutdown hook for the service"""
        # Close RabbitMQ connection
        await self.rabbit_connection.close()
        
        # Close Redis connection
        await self.cache_client.close()
        
        logger.info(f"{self.config.service_name} service stopped")
    
    def include_router(
        self, 
        router: Union[APIRouter, VersionedAPIRouter], 
        prefix: Optional[str] = None, 
        tags: Optional[List[str | Enum]] = None
    ):
        """Include FastAPI router with version support"""
        if prefix is None:
            prefix = f"/{self.config.service_name}"
        
        if tags is None:
            tags = [self.config.service_name]
        
        # Handle regular APIRouter
        if isinstance(router, APIRouter) and not isinstance(router, VersionedAPIRouter):
            # Mount with default version
            versioned_prefix = f"/{self.config.api_version_prefix}{self.config.default_api_version}{prefix}"
            self.app.include_router(router, prefix=versioned_prefix, tags=tags)
            return
        
        # Handle VersionedAPIRouter
        for version in router.versions:
            # Skip unsupported versions
            if version not in self.config.supported_api_versions and version not in self.config.deprecated_api_versions:
                logger.warning(f"Router version {version} is not in supported or deprecated versions, skipping")
                continue
                
            # Add deprecation header for deprecated versions
            is_deprecated = version in self.config.deprecated_api_versions or version in router.deprecated_versions
            
            versioned_prefix = f"/{self.config.api_version_prefix}{version}{prefix}"
            
            # For deprecated versions, we clone the router and add a middleware to add deprecation header
            if is_deprecated:
                logger.info(f"Mounting deprecated API version {version} at {versioned_prefix}")
                
                # Clone router
                cloned_router = APIRouter()
                
                # Copy routes
                for route in router.routes:
                    # Add deprecation header to response
                    if isinstance(route, APIRoute):
                        # Save original response_model and other attributes
                        original_response_model = getattr(route, "response_model", None)
                        
                        # Create new route with wrapper to add deprecation header
                        def deprecated_endpoint_wrapper(endpoint):
                            async def wrapper(*args, **kwargs):
                                response = await endpoint(*args, **kwargs)
                                # In a real implementation, we would add a response middleware
                                # that adds a deprecation header, but for simplicity we just log a warning
                                logger.warning(f"Deprecated API version {version} called")
                                return response
                            return wrapper
                        
                        # Add route to cloned router
                        cloned_router.add_api_route(
                            path=route.path,
                            endpoint=deprecated_endpoint_wrapper(route.endpoint),
                            response_model=original_response_model,
                            methods=route.methods,
                            **{k: v for k, v in route.__dict__.items() 
                               if k not in ("path", "endpoint", "methods", "response_model")}
                        )
                    else:
                        # For non-APIRoute routes, just copy
                        cloned_router.routes.append(route)
                
                self.app.include_router(cloned_router, prefix=versioned_prefix, tags=tags + [f"v{version}"])
            else:
                logger.info(f"Mounting API version {version} at {versioned_prefix}")
                self.app.include_router(router, prefix=versioned_prefix, tags=tags + [f"v{version}"])
    
    def register_command_handler(self, command_class, handler):
        """Register a command handler with the CQRS system"""
        if self.cqrs:
            self.cqrs.command_bus.register(command_class, handler)
        else:
            logger.warning("CQRS registry not initialized, command handler registration deferred")
    
    def register_query_handler(self, query_class, handler):
        """Register a query handler with the CQRS system"""
        if self.cqrs:
            self.cqrs.query_bus.register(query_class, handler)
        else:
            logger.warning("CQRS registry not initialized, query handler registration deferred")
    
    def register_event_handler(self, event_class, handler):
        """Register an event handler with the CQRS system"""
        if self.cqrs:
            self.cqrs.event_bus.register(event_class, handler)
        else:
            logger.warning("CQRS registry not initialized, event handler registration deferred")
    
    def run(self):
        """Run the service"""
        uvicorn.run(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level.lower(),
        )


def create_microservice(
    service_name: str,
    port: int,
    event_subscriptions: List[str] = [],
    db_connection_string: Optional[str] = None,
    jwt_secret: Optional[str] = None,
    supported_api_versions: List[str] = [],
    deprecated_api_versions: List[str] = [],
    default_api_version: Optional[str] = None,
    lifespan: Optional[Lifespan[FastAPI]] = None,  # Use correct type
) -> BaseMicroservice:
    """Factory function to create a microservice"""
    config = MicroserviceConfig()
    config.service_name = service_name
    config.port = port
    
    if event_subscriptions:
        config.event_subscriptions = event_subscriptions
    
    if db_connection_string:
        config.db_connection_string = db_connection_string
    
    if jwt_secret:
        config.jwt_secret = jwt_secret
    else:
        # Use environment variable if available
        jwt_secret = os.environ.get("JWT_SECRET")
        if jwt_secret:
            config.jwt_secret = jwt_secret
    
    # API versioning configuration
    if supported_api_versions:
        config.supported_api_versions = supported_api_versions
    
    if deprecated_api_versions:
        config.deprecated_api_versions = deprecated_api_versions
    
    if default_api_version:
        config.default_api_version = default_api_version
    
    # Get algorithm from environment if available
    jwt_algorithm = os.environ.get("JWT_ALGORITHM")
    if jwt_algorithm:
        config.jwt_algorithm = jwt_algorithm
    
    # Get token expiry from environment if available
    access_token_expire_minutes = os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES")
    if access_token_expire_minutes:
        config.access_token_expire_minutes = int(access_token_expire_minutes)
    
    # Get CORS origins from environment if available
    cors_origins = os.environ.get("CORS_ORIGINS")
    if cors_origins:
        if cors_origins == "*":
            config.cors_origins = ["*"]
        else:
            config.cors_origins = cors_origins.split(",")
    
    return BaseMicroservice(config, lifespan)