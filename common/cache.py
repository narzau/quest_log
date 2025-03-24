import json
import logging
from typing import Any, Optional, TypeVar, Type, Dict, Union, List, cast
from datetime import timedelta

from redis.asyncio.client import Redis

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar('T')
ModelType = TypeVar('ModelType', bound=BaseModel)


class SimplePipeline:
    """Simple pipeline implementation for Redis commands when actual pipeline is not available"""
    
    def __init__(self, redis_client: Redis, prefix: str):
        self.client = redis_client
        self.prefix = prefix
        self.commands = []
        
    def _get_key(self, key: str) -> str:
        """Get prefixed key"""
        return f"{self.prefix}{key}"
        
    def incr(self, key: str):
        """Add incr to command queue"""
        self.commands.append(("incr", self._get_key(key)))
        return self
        
    def expire(self, key: str, seconds: int):
        """Add expire to command queue"""
        self.commands.append(("expire", self._get_key(key), seconds))
        return self
        
    def set(self, key: str, value: str, ex: Optional[int] = None):
        """Add set to command queue"""
        if ex is not None:
            self.commands.append(("set", self._get_key(key), value, ex))
        else:
            self.commands.append(("set", self._get_key(key), value))
        return self
        
    def get(self, key: str):
        """Add get to command queue"""
        self.commands.append(("get", self._get_key(key)))
        return self
        
    async def execute(self):
        """Execute all commands in the queue"""
        results = []
        for cmd in self.commands:
            if cmd[0] == "incr":
                results.append(await self.client.incr(cmd[1]))
            elif cmd[0] == "expire":
                results.append(await self.client.expire(cmd[1], cmd[2]))
            elif cmd[0] == "set" and len(cmd) == 3:
                results.append(await self.client.set(cmd[1], cmd[2]))
            elif cmd[0] == "set" and len(cmd) == 4:
                results.append(await self.client.set(cmd[1], cmd[2], ex=cmd[3]))
            elif cmd[0] == "get":
                results.append(await self.client.get(cmd[1]))
            # Add other commands as needed
        self.commands = []
        return results


class CacheClient:
    """Redis cache client for caching data"""
    
    def __init__(
        self, 
        host: str = "localhost", 
        port: int = 6379, 
        db: int = 0,
        prefix: str = "quest:",
        password: str = "redispassword"
    ):
        self.host = host
        self.port = port
        self.db = db
        self.prefix = prefix
        self.password = password
        self.client: Optional[Redis] = None

    async def connect(self) -> None:
        """Connect to Redis"""
        if self.client is not None:
            return
            
        logger.info(f"Connecting to Redis: {self.host}:{self.port}")
        try:
            self.client = Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
                password=self.password
            )
            # Test connection
            await self.client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            self.client = None
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self) -> None:
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            self.client = None
    
    async def _ensure_connected(self) -> Redis:
        """Ensure client is connected before operations"""
        if self.client is None:
            await self.connect()
        assert self.client is not None, "Redis client is not initialized"
        return self.client

    def _get_key(self, key: str) -> str:
        """Get prefixed key"""
        return f"{self.prefix}{key}"
        
    async def pipeline(self) -> Any:
        """Get a Redis pipeline or our simple implementation if not available"""
        client = await self._ensure_connected()
        # First try to use the native pipeline if available
        if hasattr(client, "pipeline") and callable(client.pipeline):
            try:
                return client.pipeline()
            except (ImportError, AttributeError) as e:
                logger.warning(f"Native Redis pipeline not available: {e}")
                
        # Fall back to our simple implementation
        return SimplePipeline(client, self.prefix)

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        client = await self._ensure_connected()
        result = await client.get(self._get_key(key))
        return result

    async def set(
        self, 
        key: str, 
        value: str, 
        expire: Optional[Union[int, timedelta]] = None
    ) -> None:
        """Set value in cache with optional expiry"""
        client = await self._ensure_connected()
        await client.set(self._get_key(key), value, ex=expire)
        
    async def incr(self, key: str) -> int:
        """Increment a key's integer value"""
        client = await self._ensure_connected()
        result = await client.incr(self._get_key(key))
        return result
        
    async def expire(self, key: str, seconds: int) -> bool:
        """Set a key's time to live in seconds"""
        client = await self._ensure_connected()
        result = await client.expire(self._get_key(key), seconds)
        return bool(result)
        
    async def ttl(self, key: str) -> int:
        """Get the time to live for a key in seconds"""
        client = await self._ensure_connected()
        result = await client.ttl(self._get_key(key))
        return result

    async def delete(self, key: str) -> None:
        """Delete key from cache"""
        client = await self._ensure_connected()
        await client.delete(self._get_key(key))

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        client = await self._ensure_connected()
        result = await client.exists(self._get_key(key))
        return bool(result)
        
    async def hash_set(self, key: str, field: str, value: str) -> None:
        """Set field in hash"""
        client = await self._ensure_connected()
        result = client.hset(self._get_key(key), field, value)
        # Note: hset in redis-py 5.x returns an integer, not a coroutine
        if hasattr(result, "__await__"):  # Check if it's awaitable
            await result # type: ignore
        
    async def hash_get(self, key: str, field: str) -> Optional[str]:
        """Get field from hash"""
        client = await self._ensure_connected()
        result = client.hget(self._get_key(key), field)
        # Check if the method returns an awaitable 
        if hasattr(result, "__await__"):  # Check if it's awaitable
            return await result  # type: ignore
        return result # type: ignore
        
    async def hash_get_all(self, key: str) -> Dict[str, str]:
        """Get all fields from hash"""
        client = await self._ensure_connected()
        result = client.hgetall(self._get_key(key))
        # Check if the method returns an awaitable
        if hasattr(result, "__await__"):  # Check if it's awaitable
            return await result # type: ignore
        return result # type: ignore
        
    async def set_json(
        self, 
        key: str, 
        value: Union[Dict, List, BaseModel], 
        expire: Optional[Union[int, timedelta]] = None
    ) -> None:
        """Set JSON value in cache"""
        if isinstance(value, BaseModel):
            value = value.model_dump()
        await self.set(key, json.dumps(value), expire)
        
    async def get_json(self, key: str) -> Optional[Dict]:
        """Get JSON value from cache"""
        data = await self.get(key)
        if data:
            return json.loads(data)
        return None
        
    async def cache_model(
        self, 
        key: str, 
        model: BaseModel, 
        expire: Optional[Union[int, timedelta]] = None
    ) -> None:
        """Cache Pydantic model"""
        await self.set_json(key, model, expire)
        
    async def get_model(self, key: str, model_class: Type[ModelType]) -> Optional[ModelType]:
        """Get cached Pydantic model"""
        data = await self.get_json(key)
        if data:
            return model_class.model_validate(data)
        return None
        
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate cache keys matching pattern"""
        client = await self._ensure_connected()
        pattern_key = self._get_key(pattern)
        keys = await client.keys(pattern_key)
        
        if not keys:
            return 0
            
        result = await client.delete(*keys)
        return result


# Singleton instance for use across the application
_cache_client: Optional[CacheClient] = None


async def get_cache_client(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    prefix: str = "quest:",
    password: str = "redispassword"
) -> CacheClient:
    """Get shared cache client"""
    global _cache_client
    
    if _cache_client is None:
        _cache_client = CacheClient(
            host=host,
            port=port,
            db=db,
            prefix=prefix,
            password=password
        )
        await _cache_client.connect()
    
    return _cache_client