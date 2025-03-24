import aiohttp
import asyncio
import os
import logging
import socket

from typing import Dict, List, Optional
from functools import wraps

from pydantic import BaseModel, Field
from fastapi import FastAPI

logger = logging.getLogger(__name__)


class ServiceInstance(BaseModel):
    """Model for a service instance"""
    id: str
    name: str
    host: str
    port: int
    address: str = ""
    tags: list[str] = Field(default_factory=list)
    meta: Dict[str, str] = Field(default_factory=dict)
    healthy: bool = True

    @property
    def url(self) -> str:
        """Get the URL for this service instance"""
        host = self.address or self.host
        return f"http://{host}:{self.port}"


class ServiceConfig(BaseModel):
    """Configuration for a service"""
    name: str
    id: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8000
    address: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    meta: Dict[str, str] = Field(default_factory=dict)
    health_check_path: str = "/health"
    health_check_interval: str = "15s"
    health_check_timeout: str = "5s"
    deregister_critical_service_after: str = "30s"


class DockerComposeServiceRegistry:
    """Service registry implementation using Docker Compose service names"""

    def __init__(self):
        """Initialize the Docker Compose service registry"""
        self.registered_services = {}
        self.is_connected = True  # Docker Compose DNS is always available
        logger.info("Using Docker Compose service registry")
            
    async def connect(self) -> None:
        """No-op connect method since Docker Compose DNS is always available"""
        # Nothing needs to be done
        pass
        
    async def register_service(self, config: ServiceConfig) -> bool:
        """
        Register a service
        
        Note: In Docker Compose, service registration is handled via the docker-compose.yml file.
        This method just logs the information for reference.
        """
        service_id = config.id or f"{config.name}-{socket.gethostname()}"
        
        # Just keep track of the service
        self.registered_services[service_id] = config
        
        # Log service information
        logger.info(f"Service {service_id} registered (note: actual registration happens in docker-compose.yml)")
        return True
    
    async def deregister_service(self, service_id: str) -> bool:
        """
        Deregister a service 
        
        Note: In Docker Compose, service deregistration is handled automatically.
        """
        if service_id in self.registered_services:
            del self.registered_services[service_id]
            logger.info(f"Service {service_id} deregistered from tracking")
            return True
        return False
    
    async def deregister_all_services(self) -> None:
        """
        Deregister all services
        
        Note: In Docker Compose, service deregistration is handled automatically.
        """
        self.registered_services.clear()
    
    async def discover_service(self, service_name: str) -> List[ServiceInstance]:
        """
        Discover service instances by name
        
        In Docker Compose, this uses the service name directly.
        """
        try:
            # In Docker Compose, service name is the hostname
            service_hostname = service_name
            
            # Normalize service name by removing any namespace or domain suffix
            if "." in service_name:
                service_hostname = service_name.split(".")[0]
            
            # Get the port from environment variable or use default
            port_env_var = f"{service_hostname.upper().replace('-', '_')}_SERVICE_PORT"
            port = int(os.environ.get(port_env_var, "80"))
            
            # Check if the service is healthy
            is_healthy = await self._check_service_health(service_hostname, port)
            
            instance = ServiceInstance(
                id=service_hostname,
                name=service_hostname,
                host=service_hostname,
                port=port,
                healthy=is_healthy
            )
            
            return [instance]
        except Exception as e:
            logger.error(f"Error discovering service: {e}")
            return []
    
    async def _check_service_health(self, host: str, port: int) -> bool:
        """Check if a service instance is healthy"""
        health_url = f"http://{host}:{port}/health"
        
        try:
            async with aiohttp.ClientSession() as session:
                # Fix timeout parameter to use aiohttp.ClientTimeout
                timeout = aiohttp.ClientTimeout(total=5)
                async with session.get(health_url, timeout=timeout) as response:
                    return response.status == 200
        except Exception as e:
            # If health check fails, log and assume it's unhealthy
            logger.warning(f"Health check failed for {host}:{port}: {e}")
            return False
    
    async def get_healthy_service_url(self, service_name: str) -> Optional[str]:
        """
        Get a healthy service URL
        
        In Docker Compose, this returns the service name directly
        """
        # In Docker Compose, service name is the hostname
        if "." in service_name:
            # Extract just the service name without any domain
            service_name = service_name.split(".")[0]
        
        # Get port from environment variable or use default based on service
        default_ports = {
            "user-service": "8001",
            "quest-service": "8002",
            "note-service": "8003",
            "voice-service": "8004",
            "subscription-service": "8005",
            "integration-service": "8006",
        }
        
        default_port = default_ports.get(service_name, "80")
        port_env_var = f"{service_name.upper().replace('-', '_')}_SERVICE_PORT"
        port = os.environ.get(port_env_var, default_port)
        
        service_url = f"http://{service_name}:{port}"
        return service_url
    
    async def close(self) -> None:
        """Close the registry"""
        # No resources to clean up
        pass


# Context for storing registry instance
_registry_context = {}


async def get_service_registry() -> DockerComposeServiceRegistry:
    """Get or create a service registry instance"""
    global _registry_context
    
    if 'registry' not in _registry_context:
        registry = DockerComposeServiceRegistry()
        _registry_context['registry'] = registry
    
    return _registry_context['registry']


class ServiceDiscoveryMiddleware:
    """Middleware to handle service discovery for microservices"""
    
    def __init__(self, service_name: str, service_id: Optional[str] = None):
        self.service_name = service_name
        self.service_id = service_id or f"{service_name}-{socket.gethostname()}"
        self.registry = None
    
    async def register(self, app: FastAPI) -> None:
        """Register service with service discovery"""
        try:
            self.registry = await get_service_registry()
            
            # Get service config
            config = ServiceConfig(
                name=self.service_name,
                id=self.service_id,
                port=int(os.environ.get(f"{self.service_name.upper().replace('-', '_')}_PORT", "8000")),
                host=os.environ.get(f"{self.service_name.upper().replace('-', '_')}_HOST", "0.0.0.0"),
                tags=[f"version:{os.environ.get('SERVICE_VERSION', '0.1.0')}"]
            )
            
            result = await self.registry.register_service(config)
            if not result:
                logger.warning(f"Failed to register service {self.service_name} with service discovery")
        except Exception as e:
            logger.error(f"Error in service discovery registration: {e}")
    
    async def deregister(self) -> None:
        """Deregister service from service discovery"""
        if self.registry:
            try:
                await self.registry.deregister_service(self.service_id)
            except Exception as e:
                logger.error(f"Error deregistering service: {e}")


def setup_service_discovery(app: FastAPI, service_name: str, service_id: Optional[str] = None) -> None:
    """Set up service discovery for a FastAPI application"""
    middleware = ServiceDiscoveryMiddleware(service_name, service_id)
    
    @app.on_event("startup")
    async def startup_service_discovery():
        await middleware.register(app)
    
    @app.on_event("shutdown")
    async def shutdown_service_discovery():
        await middleware.deregister()


async def discover_service_url(service_name: str) -> Optional[str]:
    """Discover a service URL by name"""
    registry = await get_service_registry()
    return await registry.get_healthy_service_url(service_name)


def with_service_discovery(target_service: str):
    """Decorator to inject service URL into function calls"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            service_url = await discover_service_url(target_service)
            if not service_url:
                raise RuntimeError(f"Service {target_service} not available")
            
            # Replace service_url parameter if present in kwargs
            if 'service_url' in kwargs:
                kwargs['service_url'] = service_url
            # Otherwise add as a new parameter
            else:
                kwargs['service_url'] = service_url
                
            return await func(*args, **kwargs)
        return wrapper
    return decorator 