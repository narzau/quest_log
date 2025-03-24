# Quest Logger Microservices

A production-grade microservices architecture for the Quest Logger application, designed with modern best practices using an event-driven, CQRS pattern with distributed tracing and comprehensive monitoring.

## Architecture Overview

- **API Gateway**: Single entry point for client requests, routing to appropriate backend services
- **User Service**: Handles user management, authentication, and authorization
- **Shared Common Library**: Core reusable components for all services
- **Messaging System**: Event-driven architecture with RabbitMQ
- **Caching Layer**: Redis for performance optimization
- **Database**: PostgreSQL with async access and migrations
- **Monitoring Stack**: Comprehensive observability with Prometheus, Grafana and Jaeger
- **Containerization**: Docker with multi-environment deployment

## Local Development Environment

This project is configured to run locally with Docker Compose, providing a simplified development experience.

### Prerequisites

Make sure you have the following tools installed:

- Docker
- Docker Compose
- Python 3.11+
- Git

### Setting Up Local Environment

We've created a helpful script `docker-dev.sh` to simplify the local development process.

```bash
# Make the script executable (if not already)
chmod +x docker-dev.sh

# View available commands
./docker-dev.sh help
```

### Starting the Environment

To start the complete local development environment:

```bash
./docker-dev.sh start
```

This command:
1. Checks for required files
2. Starts all services using Docker Compose
3. Displays URLs for accessing each service

### Development Workflow

The project follows these development patterns:

1. **Checking Status**:
   ```bash
   ./docker-dev.sh ps
   ```

2. **Viewing Logs**:
   ```bash
   # View logs for all services
   ./docker-dev.sh logs
   
   # View logs for a specific service
   ./docker-dev.sh logs api-gateway
   ```

3. **Accessing a Service Shell**:
   ```bash
   ./docker-dev.sh shell user-service
   ```

4. **Rebuilding Services**:
   ```bash
   ./docker-dev.sh rebuild
   ```

5. **Stopping the Environment**:
   ```bash
   ./docker-dev.sh stop
   ```

## Service Access

When the environment is running, you can access various services at:

- **API Gateway**: http://localhost:8000
- **RabbitMQ Management**: http://localhost:15672 (guest/guest)
- **Jaeger UI (Tracing)**: http://localhost:16686
- **Prometheus (Metrics)**: http://localhost:9090
- **Grafana (Dashboards)**: http://localhost:3000
- **Elasticsearch**: http://localhost:9200
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

## Service Configuration

### RabbitMQ Configuration

RabbitMQ is configured using configuration files instead of environment variables:

- `config/rabbitmq/rabbitmq.conf`: Main configuration file (memory limits, disk limits)
- `config/rabbitmq/advanced.config`: Advanced Erlang-based configuration
- `config/rabbitmq/enabled_plugins`: Plugins configuration

This approach follows RabbitMQ best practices and avoids deprecated environment variables.

## Service Discovery

The application uses Docker Compose networking for service discovery:

- Services can communicate with each other using their service name as the hostname
- For example, the API Gateway can reach the User Service at `http://user-service:8001`
- All services are on the same Docker network (`quest-network`)
- Environment variables in the docker-compose.yml file configure the services with the correct hostnames

## Directory Structure

- **/services/**: Contains individual microservices
  - **/api-gateway/**: API Gateway service routes requests to backend services
  - **/user-service/**: User management and authentication service

- **/common/**: Shared code library used by all services

- **/monitoring/**: Monitoring configuration
  - **/prometheus/**: Prometheus configuration
  - **/grafana/**: Grafana dashboards and datasources

- **/docs/**: Documentation files
- **/init-scripts/**: Database initialization scripts

## Troubleshooting

If you encounter issues with your local setup:

1. **Check container status**:
   ```bash
   ./docker-dev.sh ps
   ```

2. **Check service logs**:
   ```bash
   ./docker-dev.sh logs [service-name]
   ```

3. **Check if services can communicate**:
   ```bash
   ./docker-dev.sh shell api-gateway
   ping user-service
   ```

4. **Check environment variables**:
   ```bash
   ./docker-dev.sh shell [service-name]
   env | grep SERVICE
   ```

5. **Restart a specific service**:
   ```bash
   docker compose restart [service-name]
   ```

6. **Fix RabbitMQ connection issues**:
   If you encounter error messages like `RESOURCE_LOCKED - cannot obtain exclusive access to locked queue`, run:
   ```bash
   ./docker-dev.sh cleanup-rabbitmq
   ```
   This will clean up stale RabbitMQ resources and fix connection issues.

## Contributing

Please follow these guidelines when contributing to the project:

1. **Use feature branches**: Create separate branches for each feature
2. **Follow the established patterns**: Keep consistent with the project architecture
3. **Write tests**: Ensure your code is covered by tests
4. **Document your changes**: Update relevant documentation

## License

[MIT License](LICENSE) 