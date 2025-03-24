# CI/CD Pipeline Documentation

This project uses GitHub Actions for continuous integration and continuous deployment. The pipeline ensures that code changes are automatically tested, built, and deployed to appropriate environments.

## Pipeline Overview

The CI/CD process consists of two main workflows:

1. **Continuous Integration (CI)**: Triggered on pushes and pull requests to main and develop branches
2. **Continuous Deployment (CD)**: Triggered after successful CI completion on the main branch

## Continuous Integration (CI)

The CI workflow (`ci.yml`) handles code quality checks, testing, and building Docker images.

### Jobs

#### 1. Lint

- **Purpose**: Ensure code quality and style consistency
- **Tools**: flake8, black, isort, mypy
- **Actions**:
  - Install Python dependencies
  - Run linting checks for code style and quality
  - Run type checking with mypy

#### 2. Test

- **Purpose**: Verify functionality through automated tests
- **Tools**: pytest, pytest-asyncio, pytest-cov
- **Services**:
  - PostgreSQL for database tests
  - Redis for caching tests
  - RabbitMQ for messaging tests
- **Actions**:
  - Set up test environment with services
  - Run tests with coverage reporting
  - Upload coverage reports to Codecov

#### 3. Build

- **Purpose**: Create and publish Docker images
- **Tools**: Docker Buildx
- **Actions**:
  - Log in to GitHub Container Registry
  - Build Docker images for each service
  - Tag images with branch name and commit SHA
  - Push images to registry
- **Conditions**: Only runs on pushes to `main` or `develop` branches

## Continuous Deployment (CD)

The CD workflow (`cd.yml`) handles the deployment of built images to Kubernetes environments.

### Jobs

#### 1. Deploy to Development

- **Purpose**: Deploy latest code to development environment
- **Tools**: kubectl, kustomize
- **Actions**:
  - Configure Kubernetes context using secrets
  - Update image tags in Kustomize configuration
  - Apply Kubernetes manifests using Kustomize
  - Verify deployment success
- **Environment**: `development`
- **Conditions**: Only runs after successful CI workflow on main branch

#### 2. Deploy to Production

- **Purpose**: Deploy latest code to production environment
- **Tools**: kubectl, kustomize
- **Actions**:
  - Configure Kubernetes context using secrets
  - Update image tags in Kustomize configuration
  - Apply Kubernetes manifests using Kustomize
  - Verify deployment success
- **Environment**: `production`
- **Requirements**: 
  - Needs successful deployment to development
  - Requires manual approval through GitHub Environments

## Workflow Files

### CI Workflow (.github/workflows/ci.yml)

```yaml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  lint:
    # Linting job configuration...
  
  test:
    # Testing job configuration...
    
  build:
    # Building job configuration...
```

### CD Workflow (.github/workflows/cd.yml)

```yaml
name: CD

on:
  workflow_run:
    workflows: [CI]
    branches: [main]
    types:
      - completed

jobs:
  deploy-dev:
    # Development deployment configuration...
    
  deploy-prod:
    # Production deployment configuration...
```

## Required Secrets

The pipeline requires the following GitHub secrets:

- `KUBE_CONFIG`: Base64-encoded Kubernetes configuration file

## Deployment Process

1. Code is pushed to a feature branch
2. Pull request is opened against `develop` or `main`
3. CI workflow runs linting and tests
4. Pull request is reviewed and merged
5. CI workflow builds and pushes Docker images
6. CD workflow deploys to development automatically
7. After verification, CD workflow deploys to production with approval

## Rollback Process

In case of a failed deployment:

1. **Automatic Rollback**: Kubernetes will automatically roll back if a deployment fails the readiness checks
2. **Manual Rollback**: To manually rollback:
   - Find the previous working commit SHA
   - Update Kustomize image tags to the previous version
   - Apply the configuration: `kubectl apply -k k8s/overlays/[environment]/`

## Monitoring Deployments

Monitor deployments using:

1. GitHub Actions dashboard for workflow status
2. Kubernetes dashboard or `kubectl` for deployment status:
   ```bash
   kubectl get pods -n quest-logger-dev
   kubectl get pods -n quest-logger-prod
   ```
3. Application logs:
   ```bash
   kubectl logs -f deployment/api-gateway -n quest-logger-dev
   ```

## Best Practices

1. Make small, incremental changes for easier testing and rollback
2. Always write tests for new features
3. Use feature flags for large changes to enable gradual rollout
4. Monitor key metrics after deployments to detect issues early 