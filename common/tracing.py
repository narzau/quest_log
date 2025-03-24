import os
import logging
from typing import Optional, Dict, Any, List, Callable, Union
from functools import wraps

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Core OpenTelemetry imports - these should always be available
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Set up logger before trying imports that might fail
logger = logging.getLogger(__name__)

# Required instrumentation for FastAPI and HTTP clients
# These are considered core dependencies
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Flag variables for optional dependencies
SQLALCHEMY_AVAILABLE = False
AIOPIKA_AVAILABLE = False
REDIS_AVAILABLE = False
AIOHTTP_AVAILABLE = False

# Create dummy classes that log warnings when used if dependencies are missing
class DummyInstrumentor:
    """Dummy instrumentor class used when actual dependency is not available"""
    def __init__(self, name="unknown"):
        self.name = name
        
    def instrument(self, **kwargs):
        logger.warning(f"{self.name} instrumentation not available - dependency not installed")

# Try importing optional instrumentation libraries
# SQLAlchemy instrumentation
try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLAlchemyInstrumentor = lambda: DummyInstrumentor("SQLAlchemy")

# RabbitMQ instrumentation via AioPika
try:
    # This import may not be available
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
    AIOPIKA_AVAILABLE = True
except ImportError:
    AioPikaInstrumentor = lambda: DummyInstrumentor("AioPika")

# Redis instrumentation
try:
    # This import may not be available
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    REDIS_AVAILABLE = True
except ImportError:
    RedisInstrumentor = lambda: DummyInstrumentor("Redis")

# AioHttp client instrumentation
try:
    from aiohttp.client import ClientSession
    from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
    AIOHTTP_AVAILABLE = True
except ImportError:
    AioHttpClientInstrumentor = lambda: DummyInstrumentor("AioHttp")

# Create a propagator for distributed tracing context
propagator = TraceContextTextMapPropagator()


class TracingMiddleware(BaseHTTPMiddleware):
    """Middleware to ensure trace context is propagated properly"""
    
    def __init__(self, app: FastAPI, service_name: str = "app") -> None:
        super().__init__(app)
        self.service_name = service_name
        self.tracer = trace.get_tracer(self.service_name)

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # Extract the context from the incoming request headers
        ctx = propagator.extract(carrier=dict(request.headers))
        
        # Start a new span or continue from the extracted context
        with self.tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            context=ctx,
            kind=trace.SpanKind.SERVER,
        ) as span:
            # Add request attributes to the span
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            # Handle potential None value for hostname
            hostname = request.url.hostname
            if hostname is not None:
                span.set_attribute("http.host", hostname)
            span.set_attribute("http.scheme", request.url.scheme)
            span.set_attribute("http.target", request.url.path)
            
            # Add trace ID to response headers for debugging
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            
            # Check if error occurred
            if response.status_code >= 400:
                span.set_status(trace.Status(trace.StatusCode.ERROR))
            
            return response


def setup_tracing(
    app: FastAPI, 
    service_name: str,
    jaeger_host: Optional[str] = None,
    jaeger_port: Optional[int] = None,
    otlp_endpoint: Optional[str] = None,
    debug: bool = False,
) -> None:
    """Set up distributed tracing for a FastAPI application
    
    Args:
        app: FastAPI application
        service_name: Name of the service for tracing
        jaeger_host: Optional Jaeger host for trace collection
        jaeger_port: Optional Jaeger port for trace collection
        otlp_endpoint: Optional OTLP endpoint for trace collection
        debug: Whether to enable debug output to console
    """
    # Create a resource to identify this service
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: os.getenv("SERVICE_VERSION", "0.1.0"),
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.getenv("ENVIRONMENT", "development"),
    })
    
    # Create a trace provider with the resource
    provider = TracerProvider(resource=resource)
    
    # Set the global trace provider
    trace.set_tracer_provider(provider)
    
    # Add console exporter if in debug mode
    if debug:
        console_processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(console_processor)
        logger.info(f"Tracing: Console exporter enabled for {service_name}")
    
    # Add Jaeger exporter if host is provided
    if jaeger_host and jaeger_port:
        # Configure OTLPSpanExporter to point to Jaeger
        jaeger_otlp_endpoint = f"http://{jaeger_host}:{jaeger_port}"
        jaeger_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=jaeger_otlp_endpoint))
        provider.add_span_processor(jaeger_processor)
        logger.info(f"Tracing: Jaeger exporter enabled at {jaeger_otlp_endpoint}")
    
    # Add OTLP exporter if endpoint is provided (for any other collector)
    elif otlp_endpoint:
        otlp_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        provider.add_span_processor(otlp_processor)
        logger.info(f"Tracing: OTLP exporter enabled at {otlp_endpoint}")
    
    # Instrument FastAPI with OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)
    
    # Instrument HTTP client libraries
    HTTPXClientInstrumentor().instrument()
    
    # Instrument aiohttp if available
    if AIOHTTP_AVAILABLE:
        AioHttpClientInstrumentor().instrument()
    
    # Add the trace middleware - using app.middleware instead of add_middleware to fix type error
    app.middleware("http")(TracingMiddleware(app, service_name=service_name).dispatch)
    
    logger.info(f"Distributed tracing enabled for {service_name}")


def trace_function(
    span_name: str,
    service_name: Optional[str] = None,
    attributes: Optional[Dict[str, str]] = None,
) -> Callable:
    """Decorator to trace a function execution"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Get the tracer
            tracer_name = service_name or func.__module__
            tracer = trace.get_tracer(tracer_name)
            
            # Create span attributes
            span_attrs = attributes or {}
            span_attrs["function.name"] = func.__name__
            
            # Create the span
            with tracer.start_as_current_span(
                span_name or func.__name__,
                attributes=span_attrs,
            ) as span:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    # Record exception in the span
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                    raise
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Get the tracer
            tracer_name = service_name or func.__module__
            tracer = trace.get_tracer(tracer_name)
            
            # Create span attributes
            span_attrs = attributes or {}
            span_attrs["function.name"] = func.__name__
            
            # Create the span
            with tracer.start_as_current_span(
                span_name or func.__name__,
                attributes=span_attrs,
            ) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    # Record exception in the span
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                    raise
        
        # Use appropriate wrapper based on function type
        if hasattr(func, "__await__"):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def inject_trace_context(headers: Dict[str, str]) -> Dict[str, str]:
    """Inject trace context into headers for outgoing requests"""
    # Create a new dict to avoid modifying the original
    new_headers = headers.copy()
    
    # Inject trace context into the headers
    propagator.inject(carrier=new_headers)
    
    return new_headers


def extract_trace_context(headers: Dict[str, str]):
    """Extract trace context from headers"""
    return propagator.extract(carrier=headers)


def instrument_sqlalchemy(engine, service_name: str) -> None:
    """Instrument SQLAlchemy for tracing"""
    if not SQLALCHEMY_AVAILABLE:
        logger.warning("SQLAlchemy instrumentation not available - dependency not installed")
        return
        
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        service=service_name,
    )


def instrument_redis_client(client, service_name: str) -> None:
    """Instrument Redis client for tracing"""
    if not REDIS_AVAILABLE:
        logger.warning("Redis instrumentation not available - dependency not installed")
        return
        
    RedisInstrumentor().instrument(
        client=client,
        service=service_name,
    )


def instrument_rabbitmq(service_name: str) -> None:
    """Instrument RabbitMQ for tracing"""
    if not AIOPIKA_AVAILABLE:
        logger.warning("AioPika instrumentation not available - dependency not installed")
        return
        
    AioPikaInstrumentor().instrument(service=service_name)
