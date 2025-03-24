import logging
from typing import Dict, Any, Optional, List, Union
import asyncio
import time
import httpx
from fastapi import FastAPI, Request, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

from config import config
from common.auth import JWTHandler
from common.monitoring import setup_monitoring
from common.messaging import get_rabbitmq_connection
from common.cache import get_cache_client
from common.tracing import inject_trace_context, trace_function
from common.discovery import setup_service_discovery, discover_service_url, with_service_discovery
from common.health import HealthCheck, setup_health_checks, check_http_dependency, check_redis, check_rabbitmq

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Quest Logger API Gateway",
    description="API Gateway for Quest Logger microservices",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up monitoring
setup_monitoring(app, config.service_name)

# Set up service discovery
setup_service_discovery(app, config.service_name)

# JWT handler
jwt_handler = JWTHandler(
    config.jwt_secret,
    config.jwt_algorithm,
    config.access_token_expire_minutes,
)

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")

# HTTP client for forwarding requests
http_client = httpx.AsyncClient(timeout=30.0)

# Service URL mapping
service_map = {service.prefix: service for service in config.services}

# Authentication dependency
async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """Verify JWT token and return user info"""
    try:
        # Verify the token
        payload = jwt_handler.verify_token(token)
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Optional auth dependency for endpoints that can work with or without auth
async def get_optional_user(
    authorization: Optional[str] = Header(None)
) -> Optional[Dict[str, Any]]:
    """Optionally verify JWT token and return user info"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            payload = jwt_handler.verify_token(token)
            return payload
        except JWTError:
            return None
    return None


@trace_function("route_request", service_name="api-gateway")
async def route_request(
    request: Request,
    backend_url: str,
    user: Optional[Dict[str, Any]] = None,
    use_service_discovery: bool = False,
    service_name: Optional[str] = None,
    path_prefix: Optional[str] = None,
) -> Union[StreamingResponse, JSONResponse]:
    """Route a request to a backend service"""
    client_host = request.client.host if request.client else "unknown"
    client_port = request.client.port if request.client else "unknown"
    
    logger.info(f"Routing request from {client_host}:{client_port} to {backend_url}")
    
    # Clone the headers
    headers = dict(request.headers)
    
    # Use service discovery if enabled
    if use_service_discovery and service_name:
        service_url = await discover_service_url(service_name)
        if service_url:
            backend_url = service_url
            logger.info(f"Using service discovery: {service_name} -> {backend_url}")
    
    # Determine the path to use
    if path_prefix:
        # Use the provided path prefix
        backend_path = path_prefix
    else:
        # Otherwise use the full path from the request
        backend_path = request.url.path
    
    # Make sure the path starts with a slash
    if not backend_path.startswith("/"):
        backend_path = "/" + backend_path
        
    # Remove ending slash from backend_url if present
    if backend_url.endswith('/'):
        backend_url = backend_url[:-1]
    
    # Build target URL - ensure there's no double slashes
    target_url = f"{backend_url}{backend_path}"
    
    # Copy headers except 'host'
    headers.pop("host", None)
    
    # Add user information to headers if available
    if user and isinstance(user, dict):
        # Safely extract user information
        user_id = user.get("id", "")
        headers["X-User-ID"] = str(user_id) if user_id else ""
        headers["X-User-Email"] = user.get("email", "")
        headers["X-User-Role"] = user.get("role", "")
    
    # Inject tracing context into headers for distributed tracing
    headers = inject_trace_context(headers)
    
    # Get request body
    body = await request.body()
    
    # Forward the request
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params,
                follow_redirects=True,
            )
            
            # Log the response status code
            logger.info(f"Forwarded request to {target_url} - Status: {response.status_code}")
            
            # Get response content
            content = await response.aread()
            
            # Create a new response without streaming to avoid the issues
            # that were happening with the incomplete read errors
            response_headers = dict(response.headers)
            return JSONResponse(
                content=response.json() if response.headers.get("content-type", "").startswith("application/json") else {"data": str(content, 'utf-8')},
                status_code=response.status_code,
                headers=response_headers
            )
            
    except httpx.RequestError as e:
        logger.error(f"Error routing request to {target_url}: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "service_unavailable", "message": f"Service unavailable: {str(e)}"},
        )


@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    # Connect to RabbitMQ
    rabbitmq = await get_rabbitmq_connection(
        host=config.rabbitmq_host,
        port=config.rabbitmq_port,
        user=config.rabbitmq_user,
        password=config.rabbitmq_pass,
        service_name=config.service_name
    )
    
    # Connect to Redis
    cache = await get_cache_client(
        host=config.redis_host,
        port=config.redis_port,
        prefix=f"{config.service_name}:"
    )
    
    # Set up health check
    health_check = HealthCheck(config.service_name, "0.1.0")
    
    # Add dependency checks
    # Check Redis
    health_check.add_dependency_check(
        "redis", 
        lambda: check_redis(config.redis_host, config.redis_port)
    )
    
    # Check RabbitMQ
    health_check.add_dependency_check(
        "rabbitmq",
        lambda: check_rabbitmq(
            config.rabbitmq_host, 
            config.rabbitmq_port, 
            config.rabbitmq_user, 
            config.rabbitmq_pass
        )
    )
    
    # Check each service
    for service in config.services:
        health_check.add_dependency_check(
            f"service_{service.name}",
            lambda url=f"{service.url}/health": check_http_dependency(url)
        )
    
    # Set up health check endpoints
    setup_health_checks(app, health_check)
    
    logger.info("API Gateway started")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    await http_client.aclose()
    logger.info("API Gateway shut down")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": config.service_name}


@app.api_route("/api/v1/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def auth_route(
    request: Request,
    path: str,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """Route auth requests to user service"""
    user_service = next((s for s in config.services if s.name == "user"), None)
    if not user_service:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "service_unavailable", "message": "User service unavailable"},
        )
    
    # The user service expects a path format of /v1/auth/{action} not /api/v1/auth/{action}
    logger.info(f"Auth route called with path: {path}")
    
    # Include the path parameter in the path prefix - this ensures that /api/v1/auth/token gets routed to /v1/auth/token
    path_prefix = f"/v1/auth/{path}"
    
    return await route_request(
        request, 
        backend_url=user_service.url, 
        user=user, 
        use_service_discovery=True, 
        service_name="user-service",
        path_prefix=path_prefix  # Use the complete path with the path parameter
    )


@app.api_route("/api/v1/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_endpoint(
    request: Request,
    service: str,
    path: str,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """Proxy endpoint for API requests"""
    # Map 'users' to 'user' since the service config uses 'user' but the URL uses 'users'
    service_name = service
    if service == "users":
        service_name = "user"
    
    # Get service config
    service_config = next((s for s in config.services if s.name == service_name), None)
    if not service_config:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "service_not_found", "message": f"Service '{service}' not found"},
        )
    
    # Determine the right path prefix based on the service
    # For user service, use /v1 prefix instead of /api/v1
    path_prefix = None
    if service_name == "user":
        path_prefix = f"/v1/{path}"
    
    logger.info(f"Routing request to service: {service_name}, path: {path}, with prefix: {path_prefix}")
    
    # Route the request
    return await route_request(
        request,
        backend_url=service_config.url,
        user=user,
        use_service_discovery=True,
        service_name=f"{service_name}-service",
        path_prefix=path_prefix
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Quest Logger API Gateway",
        "version": "0.1.0",
        "services": [s.name for s in config.services],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)