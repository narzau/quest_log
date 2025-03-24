import inspect
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, Optional, Type, TypeVar, Union, get_type_hints

from pydantic import BaseModel, ValidationError, validator

from common.messaging import RabbitMQConnection
from common.resilience import circuit_breaker, CircuitBreakerConfig

logger = logging.getLogger(__name__)

# Type variables for command and query handlers
TCommand = TypeVar('TCommand', bound=BaseModel)
TCommandResult = TypeVar('TCommandResult')
TQuery = TypeVar('TQuery', bound=BaseModel)
TQueryResult = TypeVar('TQueryResult')
TEvent = TypeVar('TEvent', bound=BaseModel)


class CommandResult(BaseModel, Generic[TCommandResult]):
    """Standard response model for command handlers"""
    success: bool
    message: Optional[str] = None
    data: Optional[TCommandResult] = None
    errors: Optional[list[str]] = None


class QueryResult(BaseModel, Generic[TQueryResult]):
    """Standard response model for query handlers"""
    success: bool
    data: Optional[TQueryResult] = None
    message: Optional[str] = None
    errors: Optional[list[str]] = None


class CommandHandler(Generic[TCommand, TCommandResult], ABC):
    """Base class for command handlers"""
    
    @abstractmethod
    async def handle(self, command: TCommand) -> CommandResult[TCommandResult]:
        """Handle the command and return a result"""
        pass


class QueryHandler(Generic[TQuery, TQueryResult], ABC):
    """Base class for query handlers"""
    
    @abstractmethod
    async def handle(self, query: TQuery) -> QueryResult[TQueryResult]:
        """Handle the query and return a result"""
        pass


class EventHandler(Generic[TEvent], ABC):
    """Base class for event handlers"""
    
    @abstractmethod
    async def handle(self, event: TEvent) -> None:
        """Handle the event"""
        pass


class CommandBus:
    """
    Command bus that routes commands to their handlers
    
    Features:
    - Type-safe command dispatching
    - Centralized command validation
    - Circuit breaker integration
    - Command logging and monitoring
    """
    
    def __init__(self, rabbitmq: Optional[RabbitMQConnection] = None):
        self._handlers: Dict[Type[BaseModel], CommandHandler] = {}
        self._rabbitmq = rabbitmq
    
    def register(self, command_type: Type[TCommand], handler: CommandHandler[TCommand, Any]) -> None:
        """Register a handler for a specific command type"""
        if command_type in self._handlers:
            logger.warning(f"Overriding existing handler for command type: {command_type.__name__}")
        
        self._handlers[command_type] = handler
        logger.info(f"Registered handler for command: {command_type.__name__}")
        
        # Register with RabbitMQ if available
        if self._rabbitmq:
            async def command_rabbit_handler(data: Dict[str, Any]) -> None:
                try:
                    # Validate and create command object
                    command = command_type(**data)
                    # Execute the command
                    await self.execute(command)
                except ValidationError as e:
                    logger.error(f"Validation error for command {command_type.__name__}: {str(e)}")
                except Exception as e:
                    logger.exception(f"Error handling command {command_type.__name__}: {str(e)}")
            
            # Register the command handler with RabbitMQ
            if hasattr(self._rabbitmq, "register_command"):
                self._rabbitmq.register_command(command_type.__name__, command_rabbit_handler)
    
    @circuit_breaker(
        name="command_bus_execute",
        config=CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=30.0
        ),
        fallback_value=None
    )
    async def execute(self, command: BaseModel) -> CommandResult[Any]:
        """Execute a command by routing it to the appropriate handler"""
        command_type = type(command)
        
        if command_type not in self._handlers:
            logger.error(f"No handler registered for command: {command_type.__name__}")
            return CommandResult(
                success=False,
                message=f"No handler found for command: {command_type.__name__}"
            )
        
        handler = self._handlers[command_type]
        
        try:
            logger.debug(f"Executing command: {command_type.__name__}")
            result = await handler.handle(command)
            logger.debug(f"Command executed: {command_type.__name__}, success: {result.success}")
            return result
        except Exception as e:
            logger.exception(f"Error executing command {command_type.__name__}: {str(e)}")
            return CommandResult(
                success=False,
                message=f"Error executing command: {str(e)}",
                errors=[str(e)]
            )


class QueryBus:
    """
    Query bus that routes queries to their handlers
    
    Features:
    - Type-safe query dispatching
    - Centralized query validation
    - Circuit breaker integration
    - Query logging and monitoring
    """
    
    def __init__(self, rabbitmq: Optional[RabbitMQConnection] = None):
        self._handlers: Dict[Type[BaseModel], QueryHandler] = {}
        self._rabbitmq = rabbitmq
    
    def register(self, query_type: Type[TQuery], handler: QueryHandler[TQuery, Any]) -> None:
        """Register a handler for a specific query type"""
        if query_type in self._handlers:
            logger.warning(f"Overriding existing handler for query type: {query_type.__name__}")
        
        self._handlers[query_type] = handler
        logger.info(f"Registered handler for query: {query_type.__name__}")
        
        # Register with RabbitMQ if available
        if self._rabbitmq:
            async def query_rabbit_handler(data: Dict[str, Any]) -> Any:
                try:
                    # Validate and create query object
                    query = query_type(**data)
                    # Execute the query
                    result = await self.execute(query)
                    return result.dict()
                except ValidationError as e:
                    logger.error(f"Validation error for query {query_type.__name__}: {str(e)}")
                    return QueryResult(
                        success=False,
                        message=f"Validation error: {str(e)}",
                        errors=[str(e)]
                    ).dict()
                except Exception as e:
                    logger.exception(f"Error handling query {query_type.__name__}: {str(e)}")
                    return QueryResult(
                        success=False,
                        message=f"Error: {str(e)}",
                        errors=[str(e)]
                    ).dict()
            
            # Register the query handler with RabbitMQ
            if hasattr(self._rabbitmq, "register_query"):
                self._rabbitmq.register_query(query_type.__name__, query_rabbit_handler)
    
    @circuit_breaker(
        name="query_bus_execute", 
        config=CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=30.0
        ),
        fallback_value=None
    )
    async def execute(self, query: BaseModel) -> QueryResult[Any]:
        """Execute a query by routing it to the appropriate handler"""
        query_type = type(query)
        
        if query_type not in self._handlers:
            logger.error(f"No handler registered for query: {query_type.__name__}")
            return QueryResult(
                success=False,
                message=f"No handler found for query: {query_type.__name__}"
            )
        
        handler = self._handlers[query_type]
        
        try:
            logger.debug(f"Executing query: {query_type.__name__}")
            result = await handler.handle(query)
            logger.debug(f"Query executed: {query_type.__name__}, success: {result.success}")
            return result
        except Exception as e:
            logger.exception(f"Error executing query {query_type.__name__}: {str(e)}")
            return QueryResult(
                success=False,
                message=f"Error executing query: {str(e)}",
                errors=[str(e)]
            )


class EventBus:
    """
    Event bus for publishing and subscribing to events
    
    Features:
    - Type-safe event dispatching
    - Multiple subscribers per event
    - Asynchronous event processing
    """
    
    def __init__(self, rabbitmq: Optional[RabbitMQConnection] = None):
        self._handlers: Dict[Type[BaseModel], list[EventHandler]] = {}
        self._rabbitmq = rabbitmq
    
    def register(self, event_type: Type[TEvent], handler: EventHandler[TEvent]) -> None:
        """Register a handler for a specific event type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append(handler)
        logger.info(f"Registered handler for event: {event_type.__name__}")
        
        # Register with RabbitMQ if available
        if self._rabbitmq and len(self._handlers[event_type]) == 1:  # Only register once with RabbitMQ
            async def event_rabbit_handler(data: Dict[str, Any]) -> None:
                try:
                    # Validate and create event object
                    event = event_type(**data)
                    # Publish the event locally
                    await self.publish(event)
                except ValidationError as e:
                    logger.error(f"Validation error for event {event_type.__name__}: {str(e)}")
                except Exception as e:
                    logger.exception(f"Error handling event {event_type.__name__}: {str(e)}")
            
            # Subscribe to the event with RabbitMQ
            if hasattr(self._rabbitmq, "subscribe_event"):
                self._rabbitmq.subscribe_event(event_type.__name__, event_rabbit_handler)
    
    async def publish(self, event: BaseModel) -> None:
        """Publish an event to all registered handlers"""
        event_type = type(event)
        
        # Publish to RabbitMQ if available
        if self._rabbitmq and hasattr(self._rabbitmq, "publish_event"):
            try:
                await self._rabbitmq.publish_event(
                    event_name=event_type.__name__,
                    data=event.dict()
                )
                logger.debug(f"Published event to message broker: {event_type.__name__}")
            except Exception as e:
                logger.exception(f"Error publishing event to message broker: {str(e)}")
        
        # Execute local handlers
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    await handler.handle(event)
                except Exception as e:
                    logger.exception(f"Error handling event {event_type.__name__}: {str(e)}")


class CQRSRegistry:
    """Registry for CQRS components"""
    
    def __init__(self, rabbitmq: Optional[RabbitMQConnection] = None):
        self.command_bus = CommandBus(rabbitmq)
        self.query_bus = QueryBus(rabbitmq)
        self.event_bus = EventBus(rabbitmq)


# Function decorator for command handlers
def command_handler(registry: CQRSRegistry, command_class: Type[BaseModel]):
    """
    Decorator for command handler methods
    
    Usage:
        @command_handler(registry, CreateUserCommand)
        async def handle_create_user(self, command: CreateUserCommand) -> CommandResult[User]:
            # Command handling logic here
            return CommandResult(success=True, data=user)
    """
    def decorator(handler_func):
        class FunctionCommandHandler(CommandHandler):
            async def handle(self, command):
                return await handler_func(self, command)
        
        # Create handler instance and register
        handler_instance = FunctionCommandHandler()
        registry.command_bus.register(command_class, handler_instance)
        
        # Return the original function
        return handler_func
    
    return decorator


# Function decorator for query handlers
def query_handler(registry: CQRSRegistry, query_class: Type[BaseModel]):
    """
    Decorator for query handler methods
    
    Usage:
        @query_handler(registry, GetUserQuery)
        async def handle_get_user(self, query: GetUserQuery) -> QueryResult[User]:
            # Query handling logic here
            return QueryResult(success=True, data=user)
    """
    def decorator(handler_func):
        class FunctionQueryHandler(QueryHandler):
            async def handle(self, query):
                return await handler_func(self, query)
        
        # Create handler instance and register
        handler_instance = FunctionQueryHandler()
        registry.query_bus.register(query_class, handler_instance)
        
        # Return the original function
        return handler_func
    
    return decorator


# Function decorator for event handlers
def event_handler(registry: CQRSRegistry, event_class: Type[BaseModel]):
    """
    Decorator for event handler methods
    
    Usage:
        @event_handler(registry, UserCreatedEvent)
        async def handle_user_created(self, event: UserCreatedEvent) -> None:
            # Event handling logic here
    """
    def decorator(handler_func):
        class FunctionEventHandler(EventHandler):
            async def handle(self, event):
                await handler_func(self, event)
        
        # Create handler instance and register
        handler_instance = FunctionEventHandler()
        registry.event_bus.register(event_class, handler_instance)
        
        # Return the original function
        return handler_func
    
    return decorator 