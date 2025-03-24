import json
import logging
import uuid
from enum import Enum
from typing import Any, Dict, Optional, Callable, TypeVar, Generic, Union, List

import aio_pika
from pydantic import BaseModel, Field

from common.resilience import circuit_breaker, CircuitBreakerConfig

logger = logging.getLogger(__name__)

T = TypeVar('T')


class MessageType(str, Enum):
    COMMAND = "command"
    EVENT = "event"
    QUERY = "query"
    RESPONSE = "response"


class Message(BaseModel, Generic[T]):
    """Base message structure for all RabbitMQ messages"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    name: str
    data: T
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None


class RabbitMQConnection:
    """RabbitMQ connection manager"""
    
    def __init__(
        self, 
        host: str = "localhost", 
        port: int = 5672, 
        user: str = "guest", 
        password: str = "guest",
        service_name: str = "service",
        callback_queue: Optional[str] = None
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.service_name = service_name
        self.callback_queue_name = callback_queue or f"{self.service_name}_callback"
        self.connection = None
        self.channel = None
        self.exchange = None
        self.callback_queue = None
        self.futures = {}
        self.response_consumers = {}
        self.event_handlers = {}
        self.command_handlers = {}
        self.query_handlers = {}

    async def connect(self) -> None:
        """Establish connection to RabbitMQ"""
        logger.info(f"Connecting to RabbitMQ: {self.host}:{self.port}")
        self.connection = await aio_pika.connect_robust(
            host=self.host,
            port=self.port,
            login=self.user,
            password=self.password
        )
        self.channel = await self.connection.channel()
        
        # Declare the main topic exchange
        self.exchange = await self.channel.declare_exchange(
            "quest_logger", 
            aio_pika.ExchangeType.TOPIC,
            durable=True
        )
        
        # Create service-specific queue for receiving direct messages
        queue = await self.channel.declare_queue(
            f"{self.service_name}_queue",
            durable=True
        )
        
        # Bind the queue to service-specific routing keys
        await queue.bind(self.exchange, routing_key=f"command.{self.service_name}.#")
        await queue.bind(self.exchange, routing_key=f"query.{self.service_name}.#")
        
        # Start consuming messages
        await queue.consume(self._process_message) # type: ignore
        
        # Ensure the callback queue name is truly unique by adding a UUID
        unique_callback_name = f"{self.callback_queue_name}_{uuid.uuid4()}"
        logger.info(f"Declaring callback queue: {unique_callback_name}")
        
        # Create callback queue for RPC patterns
        self.callback_queue = await self.channel.declare_queue(
            unique_callback_name,
            exclusive=True,
            auto_delete=True,
            durable=False
        )
        await self.callback_queue.consume(self._process_response) # type: ignore
        
        logger.info(f"Connected to RabbitMQ, service: {self.service_name}")

    async def close(self) -> None:
        """Close RabbitMQ connection"""
        if self.connection:
            await self.connection.close()
            self.connection = None
            self.channel = None
            self.exchange = None

    async def _process_message(self, message: aio_pika.IncomingMessage) -> None:
        """Process incoming messages and route to appropriate handlers"""
        async with message.process():
            try:
                body = json.loads(message.body.decode())
                msg_type = body.get("type")
                msg_name = body.get("name")
                
                logger.debug(f"Received message: {msg_type}.{msg_name}")
                
                if msg_type == MessageType.COMMAND:
                    await self._handle_command(body)
                elif msg_type == MessageType.QUERY:
                    await self._handle_query(body, message)
                elif msg_type == MessageType.EVENT:
                    await self._handle_event(body)
                else:
                    logger.warning(f"Unknown message type: {msg_type}")
            
            except Exception as e:
                logger.exception(f"Error processing message: {e}")

    async def _process_response(self, message: aio_pika.IncomingMessage) -> None:
        """Process response messages for RPC calls"""
        async with message.process():
            try:
                correlation_id = message.correlation_id
                if correlation_id in self.futures:
                    future = self.futures.pop(correlation_id)
                    body = json.loads(message.body.decode())
                    future.set_result(body)
                else:
                    logger.warning(f"Received response with unknown correlation_id: {correlation_id}")
            except Exception as e:
                logger.exception(f"Error processing response: {e}")

    async def _handle_command(self, body: Dict[str, Any]) -> None:
        """Process command messages"""
        command_name = body.get("name")
        handler = self.command_handlers.get(command_name)
        
        if handler:
            await handler(body.get("data"))
        else:
            logger.warning(f"No handler for command: {command_name}")

    async def _handle_query(self, body: Dict[str, Any], message: aio_pika.IncomingMessage) -> None:
        """Process query messages and send response"""
        query_name = body.get("name")
        handler = self.query_handlers.get(query_name)
        
        if handler:
            try:
                result = await handler(body.get("data"))
                
                # Send response
                response = Message(
                    type=MessageType.RESPONSE,
                    name=f"{query_name}_response",
                    data=result,
                    correlation_id=body.get("id")
                )
                
                await self.exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(response.dict()).encode(),
                        correlation_id=body.get("id"),
                        reply_to=body.get("reply_to")
                    ),
                    routing_key=body.get("reply_to")
                )
            except Exception as e:
                logger.exception(f"Error handling query {query_name}: {e}")
        else:
            logger.warning(f"No handler for query: {query_name}")

    async def _handle_event(self, body: Dict[str, Any]) -> None:
        """Process event messages"""
        event_name = body.get("name")
        handlers = self.event_handlers.get(event_name, [])
        
        for handler in handlers:
            try:
                await handler(body.get("data"))
            except Exception as e:
                logger.exception(f"Error handling event {event_name}: {e}")

    @circuit_breaker(
        name="rabbitmq_publish_event",
        config=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=10.0
        ),
        fallback_value=None
    )
    async def publish_event(self, event_name: str, data: Any, routing_key: Optional[str] = None) -> None:
        """Publish an event message"""
        if routing_key is None:
            routing_key = f"event.{event_name}"
            
        message = Message(
            type=MessageType.EVENT,
            name=event_name,
            data=data
        )
        
        await self.exchange.publish(
            aio_pika.Message(body=json.dumps(message.dict()).encode()),
            routing_key=routing_key
        )
        
        logger.debug(f"Published event: {event_name}, routing_key: {routing_key}")

    @circuit_breaker(
        name="rabbitmq_send_command",
        config=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=10.0
        ),
        fallback_value=None
    )
    async def send_command(self, service: str, command_name: str, data: Any) -> None:
        """Send a command to a specific service"""
        routing_key = f"command.{service}.{command_name}"
        
        message = Message(
            type=MessageType.COMMAND,
            name=command_name,
            data=data
        )
        
        await self.exchange.publish(
            aio_pika.Message(body=json.dumps(message.dict()).encode()),
            routing_key=routing_key
        )
        
        logger.debug(f"Sent command: {command_name} to {service}")

    @circuit_breaker(
        name="rabbitmq_send_query",
        config=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=10.0
        ),
        fallback_value=None
    )
    async def send_query(self, service: str, query_name: str, data: Any) -> Any:
        """Send a query to a specific service and wait for response"""
        from asyncio import Future
        
        routing_key = f"query.{service}.{query_name}"
        correlation_id = str(uuid.uuid4())
        future = Future()
        
        self.futures[correlation_id] = future
        
        message = Message(
            type=MessageType.QUERY,
            name=query_name,
            data=data,
            correlation_id=correlation_id,
            reply_to=self.callback_queue.name
        )
        
        await self.exchange.publish(
            aio_pika.Message(
                body=json.dumps(message.dict()).encode(),
                correlation_id=correlation_id,
                reply_to=self.callback_queue.name
            ),
            routing_key=routing_key
        )
        
        logger.debug(f"Sent query: {query_name} to {service}")
        
        # Wait for response
        try:
            response = await future
            return response.get("data")
        except Exception as e:
            logger.exception(f"Error waiting for query response: {e}")
            raise

    def subscribe_event(self, event_name: str, handler: Callable) -> None:
        """Subscribe to events with a specific name"""
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(handler)
        logger.debug(f"Subscribed to event: {event_name}")
        
    async def subscribe_to_events(self, event_patterns: List[str]) -> None:
        """Subscribe to events with routing patterns"""
        queue = await self.channel.declare_queue(
            f"{self.service_name}_events",
            durable=True
        )
        
        for pattern in event_patterns:
            await queue.bind(self.exchange, routing_key=f"event.{pattern}")
        
        await queue.consume(self._process_message)
        logger.info(f"Subscribed to event patterns: {event_patterns}")

    def register_command(self, command_name: str, handler: Callable) -> None:
        """Register a handler for a specific command"""
        self.command_handlers[command_name] = handler
        logger.debug(f"Registered command handler: {command_name}")

    def register_query(self, query_name: str, handler: Callable) -> None:
        """Register a handler for a specific query"""
        self.query_handlers[query_name] = handler
        logger.debug(f"Registered query handler: {query_name}")


# Singleton instance for use across the application
_rabbit_connection = None


async def get_rabbitmq_connection(
    host: str = "localhost",
    port: int = 5672,
    user: str = "guest",
    password: str = "guest",
    service_name: str = "service",
    callback_queue: Optional[str] = None
) -> RabbitMQConnection:
    """Get a RabbitMQ connection with circuit breaker"""
    
    import os
    import time
    import aiohttp
    
    # Use environment variable for callback queue if available
    env_callback_queue = os.environ.get("RABBITMQ_CALLBACK_QUEUE")
    if env_callback_queue and not callback_queue:
        callback_queue = env_callback_queue
        logger.info(f"Using callback queue from environment: {callback_queue}")
    
    # Create the connection
    _rabbit_connection = RabbitMQConnection(
        host=host,
        port=port,
        user=user,
        password=password,
        service_name=service_name,
        callback_queue=callback_queue
    )
    
    # Connect with circuit breaker
    try:
        await _rabbit_connection.connect()
    except Exception as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        
        # If we hit a ChannelLockedResource error, try to clean up stale queues
        if "RESOURCE_LOCKED" in str(e):
            try:
                logger.warning("Detected locked resource, attempting to clean up stale queues...")
                # Sleep a bit to allow other connections to stabilize
                time.sleep(2)
                
                # Use the management API to clean up
                api_port = 15672  # Default management port
                mgmt_url = f"http://{host}:{api_port}/api/queues/%2F"
                
                # Find and delete stale queues related to this service
                async with aiohttp.ClientSession() as session:
                    auth = aiohttp.BasicAuth(user, password)
                    
                    # List all queues
                    async with session.get(mgmt_url, auth=auth) as resp:
                        if resp.status == 200:
                            queues = await resp.json()
                            for queue in queues:
                                if f"{service_name}_callback" in queue["name"]:
                                    # Delete the queue
                                    delete_url = f"{mgmt_url}/{queue['name']}"
                                    logger.info(f"Deleting stale queue: {queue['name']}")
                                    await session.delete(delete_url, auth=auth)
                
                # Try connecting again after cleanup
                logger.info("Retrying connection after queue cleanup...")
                time.sleep(1)
                await _rabbit_connection.connect()
            except Exception as cleanup_error:
                logger.error(f"Failed to clean up queues: {cleanup_error}")
                raise e
        else:
            raise
    
    return _rabbit_connection