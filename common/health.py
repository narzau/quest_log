import os
import logging
import socket
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Union
import asyncio

from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status for a component or the overall system"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DependencyCheck(BaseModel):
    """Health check result for a dependency"""
    name: str
    status: HealthStatus
    description: str = ""
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class HealthCheckResult(BaseModel):
    """Health check result for the overall system"""
    status: HealthStatus
    version: str
    service_name: str
    uptime_seconds: float
    dependencies: List[DependencyCheck] = Field(default_factory=list)


class HealthCheck:
    """Health check manager for microservices"""
    
    def __init__(self, service_name: str, version: str = "0.1.0"):
        self.service_name = service_name
        self.version = version
        self.start_time = time.time()
        self.dependency_checks: Dict[str, Callable] = {}
    
    def add_dependency_check(self, name: str, check_func: Callable) -> None:
        """Add a dependency check function"""
        self.dependency_checks[name] = check_func
    
    def get_uptime(self) -> float:
        """Get service uptime in seconds"""
        return time.time() - self.start_time
    
    async def check_health(self) -> HealthCheckResult:
        """Perform full health check"""
        dependencies = []
        overall_status = HealthStatus.HEALTHY
        
        # Check all dependencies
        for name, check_func in self.dependency_checks.items():
            try:
                start_time = time.time()
                check_result = await check_func()
                latency = (time.time() - start_time) * 1000  # Convert to ms
                
                if isinstance(check_result, tuple) and len(check_result) >= 2:
                    status, description = check_result[0], check_result[1]
                    details = check_result[2] if len(check_result) > 2 else {}
                elif isinstance(check_result, dict):
                    status = check_result.get("status", HealthStatus.UNKNOWN)
                    description = check_result.get("description", "")
                    details = check_result.get("details", {})
                else:
                    status = HealthStatus.HEALTHY if check_result else HealthStatus.UNHEALTHY
                    description = "Check completed" if check_result else "Check failed"
                    details = {}
                
                dependency = DependencyCheck(
                    name=name,
                    status=status,
                    description=description,
                    latency_ms=round(latency, 2),
                    details=details
                )
                dependencies.append(dependency)
                
                # Update overall status
                if status == HealthStatus.UNHEALTHY and overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.UNHEALTHY
                elif status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED
                
            except Exception as e:
                logger.warning(f"Health check for {name} failed: {e}")
                dependencies.append(DependencyCheck(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    description=f"Check failed with error: {str(e)}",
                    latency_ms=None
                ))
                overall_status = HealthStatus.UNHEALTHY
        
        return HealthCheckResult(
            status=overall_status,
            version=self.version,
            service_name=self.service_name,
            uptime_seconds=round(self.get_uptime(), 2),
            dependencies=dependencies
        )
    
    async def check_readiness(self) -> bool:
        """Quick check if service is ready to handle requests"""
        health = await self.check_health()
        return health.status != HealthStatus.UNHEALTHY
    
    async def check_liveness(self) -> bool:
        """Quick check if service is alive"""
        # Simple check that service is running
        # For liveness, we typically just need to know the service is responsive
        return True


# Common dependency checks
async def check_postgres(dsn: str) -> tuple:
    """Check PostgreSQL connection"""
    import asyncpg
    
    try:
        conn = await asyncpg.connect(dsn)
        try:
            # Execute a simple query to validate the connection
            result = await conn.fetchrow("SELECT 1 as ping")
            return (
                HealthStatus.HEALTHY,
                "PostgreSQL connection successful",
                {"ping": result["ping"] if result else None}
            )
        finally:
            await conn.close()
    except Exception as e:
        return (
            HealthStatus.UNHEALTHY,
            f"PostgreSQL connection failed: {str(e)}"
        )


async def check_redis(host: str, port: int, password: Optional[str] = None) -> tuple:
    """Check Redis connection"""
    import redis.asyncio as redis
    
    try:
        client = redis.Redis(
            host=host, 
            port=port,
            password=password,
            socket_timeout=2
        )
        
        # Test connection with a ping
        pong = await client.ping()
        await client.close()
        
        if pong:
            return (
                HealthStatus.HEALTHY,
                "Redis connection successful"
            )
        else:
            return (
                HealthStatus.DEGRADED,
                "Redis responded but didn't return expected PONG"
            )
    except redis.ConnectionError as e:
        return (
            HealthStatus.UNHEALTHY,
            f"Redis connection failed: {str(e)}"
        )
    except Exception as e:
        return (
            HealthStatus.UNHEALTHY,
            f"Redis check failed: {str(e)}"
        )


async def check_rabbitmq(host: str, port: int, user: str, password: str) -> tuple:
    """Check RabbitMQ connection"""
    import aio_pika
    
    try:
        connection = await aio_pika.connect_robust(
            host=host,
            port=port,
            login=user,
            password=password,
            timeout=2
        )
        
        try:
            # Create channel to verify the connection is working
            channel = await connection.channel()
            await channel.close()
            
            return (
                HealthStatus.HEALTHY,
                "RabbitMQ connection successful"
            )
        finally:
            await connection.close()
    except aio_pika.exceptions.ConnectionClosed as e:
        return (
            HealthStatus.UNHEALTHY,
            f"RabbitMQ connection closed: {str(e)}"
        )
    except Exception as e:
        return (
            HealthStatus.UNHEALTHY,
            f"RabbitMQ check failed: {str(e)}"
        )


async def check_http_dependency(url: str, timeout: float = 2.0) -> tuple:
    """Check HTTP dependency"""
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            
            if response.status_code < 400:
                return (
                    HealthStatus.HEALTHY,
                    f"HTTP dependency {url} responded with status {response.status_code}"
                )
            else:
                return (
                    HealthStatus.DEGRADED,
                    f"HTTP dependency {url} responded with error status {response.status_code}"
                )
    except httpx.TimeoutException:
        return (
            HealthStatus.DEGRADED,
            f"HTTP dependency {url} timed out after {timeout}s"
        )
    except Exception as e:
        return (
            HealthStatus.UNHEALTHY,
            f"HTTP dependency {url} check failed: {str(e)}"
        )


async def check_dns_resolution(hostname: str) -> tuple:
    """Check DNS resolution for a hostname"""
    try:
        # Get event loop for running in a thread
        loop = asyncio.get_event_loop()
        
        # Run getaddrinfo in a thread to avoid blocking
        info = await loop.run_in_executor(
            None, socket.getaddrinfo, hostname, None
        )
        
        if info:
            return (
                HealthStatus.HEALTHY,
                f"DNS resolution successful for {hostname}",
                {"addresses": [addr[-1][0] for addr in info]}
            )
        else:
            return (
                HealthStatus.DEGRADED,
                f"DNS resolution returned no results for {hostname}"
            )
    except socket.gaierror as e:
        return (
            HealthStatus.UNHEALTHY,
            f"DNS resolution failed for {hostname}: {str(e)}"
        )


def setup_health_checks(app: FastAPI, health_check: HealthCheck) -> None:
    """Set up health check endpoints for a FastAPI application"""
    
    @app.get("/health", tags=["Health"])
    async def health():
        """Health check endpoint for all dependencies"""
        result = await health_check.check_health()
        status_code = status.HTTP_200_OK
        
        if result.status == HealthStatus.UNHEALTHY:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif result.status == HealthStatus.DEGRADED:
            status_code = status.HTTP_200_OK  # Still 200 for degraded
        
        return Response(
            content=result.json(),
            media_type="application/json",
            status_code=status_code,
        )
    
    @app.get("/health/ready", tags=["Health"])
    async def readiness():
        """Readiness probe for kubernetes"""
        is_ready = await health_check.check_readiness()
        status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        result = {"status": "ready" if is_ready else "not_ready"}
        return Response(
            content=str(result),
            media_type="application/json",
            status_code=status_code,
        )
    
    @app.get("/health/live", tags=["Health"])
    async def liveness():
        """Liveness probe for kubernetes"""
        is_alive = await health_check.check_liveness()
        status_code = status.HTTP_200_OK if is_alive else status.HTTP_503_SERVICE_UNAVAILABLE
        result = {"status": "alive" if is_alive else "not_alive"}
        return Response(
            content=str(result),
            media_type="application/json",
            status_code=status_code,
        ) 