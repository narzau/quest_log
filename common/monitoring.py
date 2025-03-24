import asyncio
import logging
import time
from functools import wraps
from typing import Callable, Dict, Any, Optional
import os

import prometheus_client
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, Gauge
from prometheus_client.exposition import generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common.tracing import setup_tracing

logger = logging.getLogger(__name__)


# Prometheus metrics
REQUEST_COUNT = Counter(
    "app_request_count", 
    "Application Request Count",
    ["service", "endpoint", "method", "http_status"]
)

REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds", 
    "Application Request Latency",
    ["service", "endpoint", "method"]
)

ACTIVE_REQUESTS = Gauge(
    "app_active_requests", 
    "Active Requests",
    ["service"]
)

MESSAGE_COUNT = Counter(
    "app_message_count", 
    "Application Message Count",
    ["service", "message_type", "message_name"]
)

MESSAGE_LATENCY = Histogram(
    "app_message_latency_seconds", 
    "Application Message Latency",
    ["service", "message_type", "message_name"]
)

DB_QUERY_LATENCY = Histogram(
    "app_db_query_latency_seconds", 
    "Database Query Latency",
    ["service", "operation", "table"]
)

CACHE_HIT_RATIO = Gauge(
    "app_cache_hit_ratio", 
    "Cache Hit Ratio",
    ["service", "cache_type"]
)

CACHE_OPERATIONS = Counter(
    "app_cache_operations", 
    "Cache Operations",
    ["service", "operation", "result"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware to collect Prometheus metrics for HTTP requests"""
    
    def __init__(self, app: FastAPI, service_name: str = "app") -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # Increment active requests
        ACTIVE_REQUESTS.labels(service=self.service_name).inc()
        
        # Capture request path and method
        path = request.url.path
        method = request.method
        
        # Add route to path for better grouping in metrics
        if path.startswith("/api"):
            # Group /api/v1/users/123 as /api/v1/users/{id}
            path_parts = path.split("/")
            for i, part in enumerate(path_parts):
                if i > 2 and part.isdigit():  # Skip /api/v1
                    path_parts[i] = "{id}"
            path = "/".join(path_parts)
        
        # Start timer for latency measurement
        start_time = time.time()
        status_code = HTTP_500_INTERNAL_SERVER_ERROR
        
        try:
            # Process the request
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # Record request metrics
            REQUEST_COUNT.labels(
                service=self.service_name,
                endpoint=path,
                method=method,
                http_status=status_code
            ).inc()
            
            # Record latency
            REQUEST_LATENCY.labels(
                service=self.service_name,
                endpoint=path,
                method=method
            ).observe(time.time() - start_time)
            
            # Decrement active requests
            ACTIVE_REQUESTS.labels(service=self.service_name).dec()


def setup_monitoring(app: FastAPI, service_name: str) -> None:
    """Set up monitoring for a FastAPI application"""
    # Add Prometheus middleware using the FastAPI middleware pattern
    # This is the recommended way to add middleware in FastAPI
    app.middleware("http")(PrometheusMiddleware(app, service_name=service_name).dispatch)
    
    # Set up distributed tracing with our enhanced module
    jaeger_host = os.environ.get("JAEGER_HOST")
    jaeger_port = int(os.environ.get("JAEGER_PORT", "14268"))
    debug = os.environ.get("DEBUG", "False").lower() == "true"
    
    # Set up tracing with our new module
    setup_tracing(
        app=app,
        service_name=service_name,
        jaeger_host=jaeger_host,
        jaeger_port=jaeger_port,
        debug=debug
    )
    
    # Add endpoint for Prometheus metrics
    @app.get("/metrics")
    async def metrics():
        return Response(
            content=generate_latest(),
            media_type="text/plain"
        )


def time_function(
    metric: Histogram,
    labels: Dict[str, str]
) -> Callable:
    """Decorator to measure function execution time"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                metric.labels(**labels).observe(time.time() - start_time)
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                metric.labels(**labels).observe(time.time() - start_time)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def track_message(service_name: str, message_type: str, message_name: str) -> None:
    """Track message processing"""
    MESSAGE_COUNT.labels(
        service=service_name,
        message_type=message_type,
        message_name=message_name
    ).inc()


def track_cache_operation(
    service_name: str, operation: str, result: str = "success"
) -> None:
    """Track cache operation"""
    CACHE_OPERATIONS.labels(
        service=service_name,
        operation=operation,
        result=result
    ).inc()


def update_cache_hit_ratio(service_name: str, cache_type: str, ratio: float) -> None:
    """Update cache hit ratio metric"""
    CACHE_HIT_RATIO.labels(
        service=service_name,
        cache_type=cache_type
    ).set(ratio)


def track_db_query(
    service_name: str, operation: str, table: str
) -> Callable:
    """Decorator to track database query execution time"""
    return time_function(
        DB_QUERY_LATENCY,
        {"service": service_name, "operation": operation, "table": table}
    )