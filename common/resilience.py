import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar, cast

logger = logging.getLogger(__name__)

T = TypeVar("T")  # Return type for circuit-protected functions

class CircuitState(enum.Enum):
    """Circuit breaker states"""
    CLOSED = "closed"        # Normal operation, requests flow through
    OPEN = "open"            # Failure threshold exceeded, requests are blocked
    HALF_OPEN = "half_open"  # Trial period after being open, limited requests allowed


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""
    # Number of consecutive failures needed to open the circuit
    failure_threshold: int = 5
    
    # Time in seconds to wait before transitioning from OPEN to HALF_OPEN
    recovery_timeout: float = 30.0
    
    # Number of consecutive successes needed to close the circuit from HALF_OPEN
    success_threshold: int = 2
    
    # Maximum number of requests allowed in HALF_OPEN state
    half_open_max_requests: int = 1


@dataclass
class CircuitBreaker:
    """
    Circuit breaker implementation for handling failures in service communication.
    
    Implements the circuit breaker pattern to prevent cascading failures:
    - CLOSED: Normal operation, requests proceed
    - OPEN: Failure threshold exceeded, fail fast without executing
    - HALF_OPEN: Recovery state, limited requests allowed to test if issue is resolved
    """
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: Optional[float] = field(default=None, init=False)
    _half_open_requests: int = field(default=0, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Get the current state of the circuit breaker"""
        # Auto-transition from OPEN to HALF_OPEN after recovery timeout
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned from OPEN to HALF_OPEN")
        
        return self._state
    
    def record_success(self):
        """Record a successful operation"""
        if self.state == CircuitState.CLOSED:
            # Reset failure count on success in CLOSED state
            self._failure_count = 0
        elif self.state == CircuitState.HALF_OPEN:
            # Count successes in HALF_OPEN state to determine if circuit should close
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned from HALF_OPEN to CLOSED")
    
    def record_failure(self):
        """Record a failed operation"""
        self._last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit breaker '{self.name}' transitioned from CLOSED to OPEN")
        
        elif self.state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN state opens the circuit again
            self._state = CircuitState.OPEN
            self._success_count = 0
            logger.warning(f"Circuit breaker '{self.name}' transitioned from HALF_OPEN back to OPEN")
    
    def allow_request(self) -> bool:
        """Determine if a request should be allowed through"""
        current_state = self.state
        
        if current_state == CircuitState.CLOSED:
            return True
            
        if current_state == CircuitState.OPEN:
            return False
            
        # HALF_OPEN: Only allow limited number of requests
        if self._half_open_requests < self.config.half_open_max_requests:
            self._half_open_requests += 1
            return True
            
        return False


class CircuitBreakerException(Exception):
    """Exception raised when a circuit breaker is open"""
    
    def __init__(self, circuit_name: str):
        self.circuit_name = circuit_name
        super().__init__(f"Circuit breaker '{circuit_name}' is open")


class CircuitBreakerRegistry:
    """Registry of circuit breakers for different services/endpoints"""
    
    def __init__(self):
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def get_or_create(
        self, name: str, config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """Get an existing circuit breaker or create a new one"""
        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(
                name=name, 
                config=config or CircuitBreakerConfig()
            )
        return self._circuit_breakers[name]
    
    def reset(self, name: str) -> None:
        """Reset a circuit breaker to its initial state"""
        if name in self._circuit_breakers:
            del self._circuit_breakers[name]


# Global registry
_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str, config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreaker:
    """Get a circuit breaker from the global registry"""
    return _registry.get_or_create(name, config)


def reset_circuit_breaker(name: str) -> None:
    """Reset a circuit breaker in the global registry"""
    _registry.reset(name)


def circuit_breaker(
    name: str, 
    config: Optional[CircuitBreakerConfig] = None,
    fallback_value: Any = None,
    fallback_function: Optional[Callable[..., Any]] = None
):
    """
    Decorator for protecting functions with a circuit breaker.
    
    Args:
        name: Unique identifier for this circuit breaker
        config: Configuration for the circuit breaker behavior
        fallback_value: Value to return when circuit is open
        fallback_function: Function to call when circuit is open
        
    Returns:
        Decorated function with circuit breaker protection
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker(name, config)
            
            if not breaker.allow_request():
                logger.warning(
                    f"Circuit breaker '{name}' is {breaker.state.value}, "
                    f"preventing call to {func.__name__}"
                )
                
                if fallback_function is not None:
                    if asyncio.iscoroutinefunction(fallback_function):
                        return await fallback_function(*args, **kwargs)
                    return fallback_function(*args, **kwargs)
                    
                return fallback_value
            
            try:
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise e
                
        return wrapper
    return decorator 