# Quest Logger Documentation

Welcome to the Quest Logger microservices architecture documentation. This index provides navigation to all available documentation resources.

## Getting Started

- [Local Development Guide](./local_development.md) - Complete guide to setting up your local development environment
- [Kubernetes Local Development](./local_development.md#local-development-with-kubernetes) - Using Kubernetes for local development

## Architecture & Design

- [Architecture Overview](./architecture.md) - High-level architecture of the Quest Logger system
- [API Documentation](./api.md) - API specifications and examples
- [CQRS Pattern](./cqrs.md) - Command Query Responsibility Segregation implementation

## Infrastructure

- [Service Discovery](./service_discovery.md) - How services discover and communicate with each other
- [Consul to Kubernetes Migration](./consul_to_k8s_migration.md) - Migrating from Consul to Kubernetes service discovery
- [Kubernetes Deployment](./kubernetes_deployment.md) - Deploying to Kubernetes
- [CI/CD Pipeline](./ci_cd.md) - Continuous integration and deployment

## Technical Features

- [Distributed Tracing](./distributed_tracing.md) - Tracing requests across services
- [Health Checks](./health_checks.md) - Service health monitoring
- [Caching Strategy](./caching.md) - Multi-level caching implementation
- [Error Handling](./error_handling.md) - Standardized error responses
- [Authentication](./authentication.md) - JWT-based authentication system

## Development Guides

- [Adding a New Service](./adding_services.md) - Guide to adding new microservices
- [Database Migrations](./database_migrations.md) - Managing database schema changes
- [Testing Strategy](./testing.md) - Approach to testing microservices
- [Logging Best Practices](./logging.md) - Structured logging guidelines

## Operating in Production

- [Monitoring & Alerting](./monitoring.md) - Production monitoring setup
- [Scaling Services](./scaling.md) - Guidelines for scaling services
- [Backup & Recovery](./backup_recovery.md) - Data backup and recovery procedures
- [Security Best Practices](./security.md) - Security considerations

## Contributing

- [Contribution Guidelines](../CONTRIBUTING.md) - How to contribute to the project
- [Development Workflow](./development_workflow.md) - Git workflow and release process
- [Code Style Guide](./code_style.md) - Coding standards and conventions 