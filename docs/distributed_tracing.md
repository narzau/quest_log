# Distributed Tracing with OpenTelemetry

This project uses OpenTelemetry for distributed tracing across microservices. Tracing allows you to visualize the entire request flow through different services, databases, and third-party systems.

## Architecture

Our distributed tracing implementation includes the following components:

- **OpenTelemetry SDK**: Core tracing functionality
- **Jaeger**: Trace collection and visualization
- **Instrumentation Libraries**: Auto-instrumentation for popular libraries
- **Context Propagation**: W3C Trace Context format for interoperability

## Key Features

1. **End-to-End Tracing**: Track requests from the client through the API Gateway and across all microservices
2. **Automatic Instrumentation**: Auto-instrumentation for FastAPI, SQLAlchemy, Redis, RabbitMQ, etc.
3. **Manual Instrumentation**: Custom tracing for business logic with `@trace_function` decorator
4. **Trace Context Propagation**: Maintains trace context across service boundaries
5. **Attribute Collection**: Captures important metadata (HTTP method, URL, etc.)
6. **Error Detection**: Special handling for errors and exceptions

## Usage

### Decorating Service Methods

Use the `@trace_function` decorator to trace service methods:

```python
from common.tracing import trace_function

@trace_function("operation_name", service_name="my-service")
async def my_service_method():
    # Function is now traced
    ...
```

### Propagating Context in HTTP Requests

When making HTTP requests to other services, propagate the trace context:

```python
from common.tracing import inject_trace_context

# Get headers with trace context
headers = inject_trace_context(original_headers)

# Make HTTP request with these headers
response = await http_client.get(url, headers=headers)
```

### Extracting Context from Incoming Requests

When receiving requests, extract the trace context:

```python
from common.tracing import extract_trace_context

# Extract trace context
context = extract_trace_context(request.headers)
```

## Instrumenting Additional Libraries

The common tracing module provides helper functions for instrumenting:

```python
from common.tracing import instrument_sqlalchemy, instrument_redis_client, instrument_rabbitmq

# Instrument SQLAlchemy
instrument_sqlalchemy(engine, "my-service")

# Instrument Redis
instrument_redis_client(redis_client, "my-service")

# Instrument RabbitMQ
instrument_rabbitmq("my-service")
```

## Viewing Traces

1. Access the Jaeger UI at http://localhost:16686
2. Select a service from the dropdown
3. Click "Find Traces" to view available traces
4. Click on a trace to see its detailed span view

## Debugging with Traces

1. Enable debug mode with the `DEBUG=True` environment variable
2. This will output trace information to the console
3. Check logs for trace IDs that can be used in Jaeger UI

## Best Practices

1. Use descriptive span names
2. Add relevant attributes to spans
3. Properly handle and record errors
4. Apply consistent naming across services
5. Avoid creating too many spans (tracing overhead)

## Troubleshooting

- **Missing Traces**: Check that span context is being properly propagated
- **Disconnected Traces**: Verify that trace IDs are consistent across service boundaries
- **Performance Issues**: Reduce span creation or increase batch processing interval

## Additional Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/) 