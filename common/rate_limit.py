import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from common.cache import get_cache_client, CacheClient

logger = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """Rate limiting strategies"""
    FIXED_WINDOW = "fixed_window"  # Simple counter reset after window expires
    SLIDING_WINDOW = "sliding_window"  # More precise tracking with timestamp buckets
    TOKEN_BUCKET = "token_bucket"  # Token bucket algorithm with token refill rate


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    # Default: 100 requests per minute per client
    limit: int = 100
    window: int = 60  # seconds
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    
    # How many windows to track for sliding window (higher = more precision but more memory)
    bucket_count: int = 6  # 10-second buckets for a 60-second window


class RateLimiters:
    """
    Factory for different rate limiting strategies
    """
    
    @staticmethod
    async def fixed_window(
        redis: CacheClient,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int, int]:
        """
        Fixed window rate limiter
        
        Args:
            redis: Redis client
            key: Unique key for this rate limit
            limit: Maximum allowed requests in window
            window: Time window in seconds
            
        Returns:
            Tuple of (allowed, remaining, retry_after)
        """
        # Try to use pipeline for atomicity
        try:
            pipe = await redis.pipeline()
            pipe.incr(key)
            # Execute and get the current count
            results = await pipe.execute()
            current = results[0]
            
            # Set expiration on first request
            if current == 1:
                await redis.expire(key, window)
        except Exception as e:
            logger.warning(f"Pipeline failed, falling back to individual commands: {e}")
            current = await redis.incr(key)
            
            # Set expiration on first request
            if current == 1:
                await redis.expire(key, window)
        
        # If over limit, return false with retry-after header
        if current > limit:
            ttl = await redis.ttl(key)
            return False, 0, ttl if ttl > 0 else window
        
        # Return allowed with remaining count
        return True, limit - current, 0
    
    @staticmethod
    async def sliding_window(
        redis: CacheClient,
        key: str,
        limit: int,
        window: int,
        bucket_count: int
    ) -> Tuple[bool, int, int]:
        """
        Sliding window rate limiter
        
        Args:
            redis: Redis client
            key: Unique key for this rate limit
            limit: Maximum allowed requests in window
            window: Time window in seconds
            bucket_count: Number of buckets to divide the window into
            
        Returns:
            Tuple of (allowed, remaining, retry_after)
        """
        # Each window is divided into buckets for more granular expiration
        # This gives a more accurate sliding window effect
        timestamp = int(time.time())
        bucket_size = window // bucket_count
        current_bucket = timestamp // bucket_size
        
        # Increment the current bucket
        bucket_key = f"{key}:{current_bucket}"
        
        # Use a pipeline for atomicity if available
        try:
            pipe = await redis.pipeline()
            pipe.incr(bucket_key)
            pipe.expire(bucket_key, window)
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Pipeline failed, falling back to individual commands: {e}")
            await redis.incr(bucket_key)
            await redis.expire(bucket_key, window)
        
        # Get counts from all active buckets in the window
        window_start_bucket = current_bucket - bucket_count + 1
        keys = [f"{key}:{i}" for i in range(window_start_bucket, current_bucket + 1)]
        
        # Fetch all bucket values
        bucket_counts = []
        for bucket_key in keys:
            count = await redis.get(bucket_key)
            if count is not None:
                bucket_counts.append(int(count))
            else:
                bucket_counts.append(0)
        
        # Calculate total requests in the window
        total_requests = sum(bucket_counts)
        
        # Check if over limit
        if total_requests > limit:
            # Retry after 1 bucket duration (approximate)
            return False, 0, bucket_size
        
        # Return allowed with remaining count
        return True, limit - total_requests, 0
    
    @staticmethod
    async def token_bucket(
        redis: CacheClient,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int, int]:
        """
        Token bucket rate limiter
        
        Args:
            redis: Redis client
            key: Unique key for this rate limit
            limit: Maximum tokens in bucket (burst capacity)
            window: Time window in seconds to refill the entire bucket
            
        Returns:
            Tuple of (allowed, remaining, retry_after)
        """
        # Token bucket requires two values: last update time and current token count
        tokens_key = f"{key}:tokens"
        timestamp_key = f"{key}:timestamp"
        
        # Get current values
        last_tokens = await redis.get(tokens_key)
        last_timestamp = await redis.get(timestamp_key)
        
        current_time = time.time()
        
        # Default values for first request
        if last_tokens is None:
            last_tokens = str(limit)
        
        tokens_value = float(last_tokens)
            
        if last_timestamp is None:
            last_timestamp = str(current_time)
            
        timestamp_value = float(last_timestamp)
        
        # Calculate token refill based on time passed
        token_rate = limit / window  # tokens per second
        time_passed = current_time - timestamp_value
        new_tokens = min(limit, tokens_value + (time_passed * token_rate))
        
        # Try to consume a token
        if new_tokens < 1:
            # Calculate time until next token is available
            wait_time = (1 - new_tokens) / token_rate
            retry_after = int(wait_time) + 1
            return False, 0, retry_after
        
        # Consume one token and update
        new_tokens -= 1
        
        # Use a single transaction to update both values
        try:
            pipe = await redis.pipeline()
            pipe.set(tokens_key, str(new_tokens))
            pipe.set(timestamp_key, str(current_time))
            pipe.expire(tokens_key, max(window * 2, 600))  # 2x window or 10 minutes, whichever is greater
            pipe.expire(timestamp_key, max(window * 2, 600))
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Pipeline failed, falling back to individual commands: {e}")
            await redis.set(tokens_key, str(new_tokens))
            await redis.set(timestamp_key, str(current_time))
            max_idle = max(window * 2, 600)  # 2x window or 10 minutes, whichever is greater
            await redis.expire(tokens_key, max_idle)
            await redis.expire(timestamp_key, max_idle)
        
        return True, int(new_tokens), 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting API requests
    
    Features:
    - Multiple rate limiting strategies
    - Per-endpoint configuration
    - IP-based or authenticated user identification
    - Custom response for rate limited requests
    """
    
    def __init__(
        self,
        app: ASGIApp,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_prefix: str = "ratelimit:",
        default_config: Optional[RateLimitConfig] = None,
        endpoint_configs: Optional[Dict[str, RateLimitConfig]] = None,
        method_configs: Optional[Dict[str, RateLimitConfig]] = None,
        get_client_id: Optional[Callable[[Request], str]] = None,
        excluded_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_prefix = redis_prefix
        self.default_config = default_config or RateLimitConfig()
        self.endpoint_configs = endpoint_configs or {}
        self.method_configs = method_configs or {}
        self.get_client_id = get_client_id or self._default_client_id
        self.excluded_paths = excluded_paths or ["/health", "/metrics", "/docs", "/openapi.json"]
        self.redis_client = None
        self._setup_task = asyncio.create_task(self._setup_redis())
    
    async def _setup_redis(self):
        """Set up Redis connection"""
        self.redis_client = await get_cache_client(
            host=self.redis_host,
            port=self.redis_port,
            prefix=self.redis_prefix
        )
    
    @staticmethod
    def _default_client_id(request: Request) -> str:
        """Default function to get client identifier (IP address)"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return ip
    
    async def dispatch(self, request: Request, call_next):
        """Process the request through rate limiting middleware"""
        
        # Wait for Redis to be set up
        if not self.redis_client:
            await self._setup_task
        
        # Skip excluded paths
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.excluded_paths):
            return await call_next(request)
        
        # Determine which config to use for this request
        config = self.default_config
        
        # Check for endpoint-specific config
        for endpoint_pattern, endpoint_config in self.endpoint_configs.items():
            if endpoint_pattern in path:
                config = endpoint_config
                break
                
        # Check for method-specific config
        method_config = self.method_configs.get(request.method)
        if method_config:
            config = method_config
        
        # Get client identifier
        client_id = self.get_client_id(request)
        
        # Create unique key for this client and endpoint
        md5 = hashlib.md5(path.encode()).hexdigest()
        key = f"{client_id}:{md5}"
        
        # Apply rate limiting strategy
        allowed, remaining, retry_after = await self._apply_rate_limit(
            config.strategy, key, config
        )
        
        # Create response with rate limit headers
        response = await call_next(request) if allowed else self._rate_limited_response(retry_after)
        
        # Add rate limiting headers to the response
        response.headers["X-RateLimit-Limit"] = str(config.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        if retry_after > 0:
            response.headers["Retry-After"] = str(retry_after)
        
        return response
    
    async def _apply_rate_limit(
        self, strategy: RateLimitStrategy, key: str, config: RateLimitConfig
    ) -> Tuple[bool, int, int]:
        """Apply the specified rate limiting strategy"""
        
        # Ensure we have a redis client
        if not self.redis_client:
            logger.warning("Redis client not available, skipping rate limiting")
            return True, config.limit, 0
            
        redis_client = self.redis_client
        
        if strategy == RateLimitStrategy.FIXED_WINDOW:
            return await RateLimiters.fixed_window(
                redis_client, key, config.limit, config.window
            )
        
        elif strategy == RateLimitStrategy.SLIDING_WINDOW:
            return await RateLimiters.sliding_window(
                redis_client, key, config.limit, config.window, config.bucket_count
            )
        
        elif strategy == RateLimitStrategy.TOKEN_BUCKET:
            return await RateLimiters.token_bucket(
                redis_client, key, config.limit, config.window
            )
        
        # Fallback to fixed window
        return await RateLimiters.fixed_window(
            redis_client, key, config.limit, config.window
        )
    
    def _rate_limited_response(self, retry_after: int) -> JSONResponse:
        """Create a standard response for rate limited requests"""
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many requests",
                "detail": "Rate limit exceeded. Please try again later.",
                "retry_after": retry_after
            }
        )


def setup_rate_limiting(
    app: FastAPI,
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_prefix: str = "ratelimit:",
    default_limit: int = 100,
    default_window: int = 60,
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW,
    endpoint_configs: Optional[Dict[str, RateLimitConfig]] = None,
    method_configs: Optional[Dict[str, RateLimitConfig]] = None,
    get_client_id: Optional[Callable[[Request], str]] = None,
    excluded_paths: Optional[List[str]] = None,
) -> None:
    """
    Set up rate limiting for a FastAPI application
    
    Args:
        app: FastAPI application
        redis_host: Redis server hostname
        redis_port: Redis server port
        redis_prefix: Prefix for Redis keys
        default_limit: Default request limit per window
        default_window: Default time window in seconds
        strategy: Rate limiting strategy to use
        endpoint_configs: Custom configurations for specific endpoints
        method_configs: Custom configurations for specific HTTP methods
        get_client_id: Function to extract client identifier from request
        excluded_paths: Paths to exclude from rate limiting
    """
    # Create default config
    default_config = RateLimitConfig(
        limit=default_limit,
        window=default_window,
        strategy=strategy
    )
    
    # Add middleware to the application
    app.add_middleware(
        RateLimitMiddleware,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_prefix=redis_prefix,
        default_config=default_config,
        endpoint_configs=endpoint_configs or {},
        method_configs=method_configs or {},
        get_client_id=get_client_id,
        excluded_paths=excluded_paths,
    )
    
    logger.info(
        f"Rate limiting enabled with {strategy} strategy: "
        f"{default_limit} requests per {default_window} seconds"
    ) 