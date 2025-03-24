# Quest Logger: Local Development Guide

This guide provides comprehensive instructions for setting up and running the Quest Logger microservices architecture locally, both using Docker containers and directly in a local environment.

## Prerequisites

Before starting, ensure you have the following installed:

- **Docker** (20.10.x or higher)
- **Docker Compose** (v2.x or higher)
- **Python** (3.10 or higher)
- **PostgreSQL** (15.x or higher, if running services locally)
- **Git** (for cloning the repository)
- Minimum 8GB RAM recommended for Docker
- At least 10GB of free disk space

## Cloning the Repository

```bash
git clone https://github.com/yourusername/quest_log.git
cd quest_log
```

## Environment Configuration

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit the `.env` file to set appropriate values, especially:
   - `JWT_SECRET`: Use a secure random string
   - Database credentials
   - RabbitMQ credentials

## Option 1: Full Containerized Setup (Recommended)

This approach runs everything in Docker containers and is the simplest way to get started.

### Initial Setup

Run the development setup script to install dependencies and prepare the environment:

```bash
chmod +x setup_dev.sh
./setup_dev.sh
```

### Running with Docker Compose

1. Start all services:

```bash
docker-compose up -d
```

2. Check the status of all services:

```bash
docker-compose ps
```

3. View logs:

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f user-service
```

### Running Database Migrations

Even though you're using containers, you might want to run migrations manually:

```bash
# First, install the common package locally
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
cd common
pip install -e .
cd ..

# Install user-service dependencies
cd services/user-service
pip install -r requirements.txt

# Run migrations
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/user_service alembic upgrade head
```

### Stopping the Containers

```bash
# Stop without removing volumes
docker-compose down

# Stop and remove volumes (data will be lost)
docker-compose down -v
```

## Option 2: Local Development Environment

This approach is useful when you need to develop and debug services locally.

### Setting Up the Python Environment

1. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the common package in development mode:

```bash
cd common
pip install -e .
cd ..
```

### Running Support Services with Docker

Even when developing locally, it's convenient to run databases and other supporting services in Docker:

```bash
docker-compose up -d postgres redis rabbitmq elasticsearch jaeger prometheus grafana consul
```

### Running Services Locally

#### User Service

```bash
cd services/user-service
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start the service
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

#### API Gateway

```bash
cd services/api-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Database Migrations

To create a new migration after modifying models:

```bash
cd services/user-service
alembic revision --autogenerate -m "Description of changes"
alembic upgrade head
```

## Verifying Your Setup

Once everything is running, verify your setup by accessing:

- API Gateway: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- User Service: http://localhost:8001
- Jaeger UI: http://localhost:16686
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (default login: admin/admin)
- RabbitMQ Management: http://localhost:15672 (default login: guest/guest)
- Consul UI: http://localhost:8500

## Creating Your First User

You can interact with the API using curl or any API client:

```bash
# Create user
curl -X POST http://localhost:8000/api/v1/users \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "username": "testuser", "password": "securepassword"}'

# Login
curl -X POST http://localhost:8000/api/v1/users/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "securepassword"}'
```

## Troubleshooting

### Database Connection Issues

If services can't connect to the database:

1. Verify PostgreSQL is running:
   ```bash
   docker-compose ps postgres
   ```

2. Check database initialization:
   ```bash
   docker-compose exec postgres psql -U postgres -c "\l"
   ```

3. Check the logs:
   ```bash
   docker-compose logs postgres
   ```

### Service Discovery Problems

If services can't discover each other:

1. Verify Consul is running:
   ```bash
   curl http://localhost:8500/v1/catalog/services
   ```

2. Check service registrations:
   ```bash
   curl http://localhost:8500/v1/agent/services
   ```

### Container Resource Issues

If containers are crashing or performing poorly:

1. Check resource usage:
   ```bash
   docker stats
   ```

2. Increase Docker's resources in Docker Desktop settings

### Port Conflicts

If you see errors about ports already in use:

1. Check what's using the port:
   ```bash
   # Linux/macOS
   lsof -i :8000
   
   # Windows
   netstat -ano | findstr :8000
   ```

2. Stop the conflicting service or change the port in your `.env` file

## Advanced: Working with the Code

### Making Changes to Common Library

When modifying the common library:

1. Ensure it's installed in development mode:
   ```bash
   pip install -e ./common
   ```

2. After changes, restart any running services

### Adding a New Service

To create a new microservice:

1. Create a directory in the `services` folder
2. Copy the structure from an existing service like `user-service`
3. Update the service name and implementation
4. Add the service to `docker-compose.yml`
5. Add routing configuration to the API Gateway

## Performance Tuning

For better performance on development machines:

1. Reduce Elasticsearch memory:
   ```yaml
   # In docker-compose.yml
   elasticsearch:
     environment:
       - ES_JAVA_OPTS=-Xms256m -Xmx256m
   ```

2. Use fewer replicas in Kubernetes development configuration:
   ```yaml
   # In k8s/overlays/dev/kustomization.yaml
   replicas:
   - name: user-service
     count: 1
   ```

## Running Tests

To execute the test suite:

```bash
# For user-service
cd services/user-service
pytest

# With coverage
pytest --cov=. --cov-report=term-missing
```

## Further Documentation

For more detailed information, see:

- [Architecture Overview](./architecture.md)
- [API Documentation](./api.md)
- [Kubernetes Deployment](./kubernetes_deployment.md)
- [CI/CD Pipeline](./ci_cd.md)

# Local Development with Kubernetes

This guide explains how to set up and use the local development environment for the Quest Logger microservices with Kubernetes.

## Overview

The local development environment is designed to provide parity with production, using:

- **Minikube**: A local Kubernetes cluster for development
- **Docker Compose**: For supporting services (Redis, RabbitMQ, Jaeger)
- **Kustomize**: For Kubernetes configuration management
- **Docker**: For containerized microservices

## Prerequisites

Before starting, ensure you have the following installed:

- Docker
- Minikube
- kubectl
- Python 3.11+
- Git

## Setup and Usage

We've created a `local-dev.sh` script that handles all the complexity of setting up and managing your local environment.

### Basic Commands

```bash
# Make the script executable (if not already)
chmod +x local-dev.sh

# View all available commands
./local-dev.sh help
```

### Starting the Environment

To start your complete local development environment:

```bash
./local-dev.sh start
```

This will:
1. Start Minikube if not already running
2. Start supporting services with Docker Compose
3. Build Docker images for your microservices
4. Deploy everything to the Kubernetes cluster
5. Expose services and provide access URLs

### Managing Your Environment

Here are the key commands for managing your local development environment:

```bash
# Check the status of all components
./local-dev.sh status

# View logs from a specific service
./local-dev.sh logs api-gateway
./local-dev.sh logs redis

# Rebuild and redeploy after code changes
./local-dev.sh rebuild

# Open the Kubernetes dashboard in your browser
./local-dev.sh dashboard

# Stop everything when you're done
./local-dev.sh stop
```

## Architecture Details

The local development setup consists of:

### 1. Kubernetes Resources

Located in `k8s/overlays/local`, these include:
- **Namespace**: `quest-logger-local`
- **Services**: Exposing ports for communication
- **Deployments**: Running your microservices
- **ConfigMaps**: Environment-specific configuration
- **Secrets**: Sensitive information (created at runtime)

### 2. Docker Compose Resources

Located in `docker-compose.local.yaml`, these include:
- **Redis**: For caching
- **RabbitMQ**: For messaging
- **Jaeger**: For distributed tracing

### 3. Docker Images

Built from the service Dockerfiles:
- **quest-api-gateway:local**: API Gateway service
- **quest-user-service:local**: User service

## Technical Details

### How the Docker Build Works

The `local-dev.sh` script builds Docker images by:
1. Connecting to the Minikube Docker daemon (`eval $(minikube docker-env)`)
2. Building images with the Dockerfile in each service folder
3. Tagging them for local use

### How Services Communicate

Services communicate through:
1. **Kubernetes Services**: Providing stable DNS names
2. **Service Discovery**: Using the `common/discovery.py` module
3. **DNS Resolution**: `<service-name>-local.<namespace>.svc.cluster.local`

### Port Forwarding and Access

When you run `./local-dev.sh start`, the script will output URLs for accessing your services.
The API Gateway is exposed using Minikube's service exposure mechanism.

## Development Workflow

Here's a typical development workflow:

1. **Start the environment**:
   ```bash
   ./local-dev.sh start
   ```

2. **Make code changes** to your services

3. **Rebuild and deploy**:
   ```bash
   ./local-dev.sh rebuild
   ```

4. **Test your changes** using the exposed URL

5. **View logs** to debug any issues:
   ```bash
   ./local-dev.sh logs api-gateway
   ```

6. **Stop the environment** when you're done:
   ```bash
   ./local-dev.sh stop
   ```

## Troubleshooting

### Common Issues

1. **Minikube not starting**:
   ```bash
   minikube delete
   minikube start --driver=docker
   ```

2. **Service not found**:
   ```bash
   kubectl get pods -n quest-logger-local
   kubectl describe pod <pod-name> -n quest-logger-local
   ```

3. **Service discovery not working**:
   ```bash
   # Get into a pod's shell
   kubectl exec -it <pod-name> -n quest-logger-local -- sh
   # Test DNS resolution
   nslookup user-service-local.quest-logger-local.svc.cluster.local
   ```

4. **Images not updating**:
   ```bash
   # Ensure you're building with the Minikube Docker daemon
   eval $(minikube docker-env)
   docker build -t quest-api-gateway:local -f services/api-gateway/Dockerfile .
   kubectl rollout restart deployment api-gateway -n quest-logger-local
   ```

### Getting More Information

For detailed information about what's happening in your cluster:

```bash
# Check events
kubectl get events -n quest-logger-local

# Get detailed info about a pod
kubectl describe pod <pod-name> -n quest-logger-local

# Check endpoints (to verify service discovery)
kubectl get endpoints -n quest-logger-local
```

## Notes on Dockerfiles

The service Dockerfiles are configured to:

1. Use Python 3.11 for compatibility
2. Install system dependencies and Python requirements
3. Copy the common code library to `/app/common/`
4. Set the correct working directory and environment variables
5. Run the application with the appropriate command

This setup ensures that services can find shared modules and communicate properly within the Kubernetes environment. 