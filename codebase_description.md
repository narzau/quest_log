# Quest Logger Microservices Codebase Overview

You are working with a production-grade microservices architecture for the Quest Logger application, designed with modern best practices. The system uses an event-driven, CQRS pattern with distributed tracing and comprehensive monitoring.

## Overall Architecture

- **API Gateway**: Single entry point for client requests, routing to appropriate backend services
- **User Service**: Handles user management, authentication, and authorization
- **Shared Common Library**: Core reusable components for all services
- **Messaging System**: Event-driven architecture with RabbitMQ
- **Caching Layer**: Redis for performance optimization
- **Database**: PostgreSQL with async access and migrations
- **Monitoring Stack**: Comprehensive observability with Prometheus, Grafana and Jaeger
- **Containerization**: Docker with multi-environment deployment
- **Kubernetes**: Production-ready Kubernetes manifests with Kustomize

## Key Technology Patterns

1. **CQRS (Command Query Responsibility Segregation)**: Separate command and query processing
   - Commands: State-changing operations (create, update, delete)
   - Queries: Read-only operations to retrieve data
   - Events: Notifications of state changes for cross-service communication
   - Each has its own bus (CommandBus, QueryBus, EventBus) for routing

2. **Clean Architecture**:
   - Services built with layered architecture (routes → service layer → repository layer)
   - Repository pattern for database access abstraction
   - Dependency injection for testability

3. **API Versioning**:
   - All APIs support versioning (currently v1)
   - Graceful deprecation with clear messaging

4. **Distributed Tracing**:
   - OpenTelemetry integration for tracing requests across services
   - Trace context propagation for request flow visualization
   - Jaeger for trace visualization

5. **Rate Limiting**:
   - Configurable rate limiting for API protection
   - Redis-backed with multiple strategies

6. **Service Discovery**:
   - Service discovery via Consul
   - Dynamic service location

7. **Health Checks**:
   - Comprehensive health checking for each service
   - Kubernetes-compatible readiness/liveness probes

## Directory Structure

- **/services/**: Contains individual microservices
  - **/api-gateway/**: API Gateway service routes requests to backend services
  - **/user-service/**: User management and authentication service

- **/common/**: Shared code library used by all services
  - **auth.py**: JWT authentication and authorization
  - **cache.py**: Redis caching abstraction
  - **cqrs.py**: Command Query Responsibility Segregation implementation
  - **database.py**: Database connection and ORM integration
  - **discovery.py**: Service discovery integration
  - **documentation.py**: API documentation helpers
  - **errors.py**: Standardized error handling
  - **health.py**: Health check infrastructure
  - **messaging.py**: RabbitMQ messaging abstraction
  - **monitoring.py**: Prometheus metrics integration
  - **rate_limit.py**: Request rate limiting
  - **resilience.py**: Circuit breaking and retry logic
  - **service.py**: Base microservice class and utilities
  - **tracing.py**: Distributed tracing with OpenTelemetry

- **/k8s/**: Kubernetes deployment manifests
- **/docs/**: Documentation files
- **/init-scripts/**: Database initialization scripts

## Common Infrastructure

- **BaseMicroservice**: Foundation class in service.py for all microservices with standard endpoints
- **CQRS Pattern**: Implementation in cqrs.py with Command, Query, and Event buses
- **Distributed Tracing**: Implemented in tracing.py with trace context propagation
- **Health Checking**: Comprehensive implementation in health.py

## Service Implementation Pattern

Each service follows a consistent pattern:

1. **main.py**: Entry point with service configuration and startup logic
2. **config.py**: Environment-based configuration
3. **routes.py**: API route definitions
4. **models.py**: Database models
5. **schemas.py**: Pydantic schemas for validation
6. **repository.py**: Data access layer
7. **service.py**: Business logic layer
8. **cqrs.py**: Command/Query/Event definitions specific to the service

## Best Practices to Follow

1. **Maintain Service Independence**: Each service should be independently deployable
2. **Use Event-Driven Communication**: Prefer async events over direct service calls
3. **Implement Circuit Breaking**: Handle downstream service failures gracefully
4. **Leverage CQRS**: Use the CQRS pattern for all state changes
5. **Add Tracing**: Ensure new functions are traced properly
6. **Follow Repository Pattern**: Data access should go through repositories
7. **Version APIs**: All API changes should respect versioning
8. **Document Changes**: Update API documentation for changes
9. **Use Rate Limiting**: Configure appropriate rate limits for endpoints
10. **Implement Health Checks**: Add health checks for new dependencies

## Technical Debt Considerations

1. The current implementation only has the API gateway and user service fully implemented
2. Future development should extend this architecture to additional planned services
3. There is shared understanding that this is a reference architecture being built out

When implementing new features or fixing bugs, always follow the existing patterns and architecture principles established in the codebase.
