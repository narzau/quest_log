# Kubernetes Deployment Guide

This guide explains how to deploy the Quest Logger microservices to a Kubernetes cluster.

## Architecture Overview

The Quest Logger application is deployed as a set of microservices in Kubernetes:

- **API Gateway**: Front-facing service that routes requests to appropriate backend services
- **User Service**: Handles user management, authentication, and authorization
- **PostgreSQL**: Database for storing application data
- **Redis**: Caching layer for improved performance
- **RabbitMQ**: Message broker for asynchronous communication between services
- **Jaeger**: Distributed tracing collection and visualization
- **Prometheus**: Metrics collection
- **Grafana**: Dashboard visualization for monitoring

## Deployment Structure

The deployment uses Kustomize for managing environment-specific configurations:

```
k8s/
├── base/                 # Base configurations shared by all environments
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── api-gateway-deployment.yaml
│   ├── api-gateway-service.yaml
│   ├── user-service-deployment.yaml
│   ├── user-service-service.yaml
│   ├── configmap.yaml
│   └── secrets.yaml
│
└── overlays/            # Environment-specific configurations
    ├── dev/             # Development environment
    │   ├── kustomization.yaml
    │   ├── namespace.yaml
    │   └── configmap.yaml
    │
    └── prod/            # Production environment
        ├── kustomization.yaml
        ├── namespace.yaml
        ├── configmap.yaml
        └── ingress.yaml
```

## Prerequisites

- Kubernetes cluster (local or cloud-based)
- `kubectl` installed and configured
- `kustomize` installed (or use the version built into kubectl)
- Access to a container registry (GitLab, DockerHub, etc.)

## Deployment Instructions

### Initial Setup

1. Ensure proper Kubernetes context is selected:

```bash
kubectl config current-context
```

2. Create necessary namespaces and RBAC roles (if not using Kustomize):

```bash
kubectl apply -f k8s/base/namespace.yaml
```

### Deploying to Development

1. Deploy all resources to development environment:

```bash
kubectl apply -k k8s/overlays/dev/
```

2. Verify the deployment:

```bash
kubectl get pods -n quest-logger-dev
```

3. Check service status:

```bash
kubectl get services -n quest-logger-dev
```

### Deploying to Production

1. Deploy all resources to production environment:

```bash
kubectl apply -k k8s/overlays/prod/
```

2. Verify the deployment:

```bash
kubectl get pods -n quest-logger-prod
```

3. Check service and ingress status:

```bash
kubectl get services -n quest-logger-prod
kubectl get ingress -n quest-logger-prod
```

## Secrets Management

Secrets are managed separately from the repository:

1. Create secrets (replace placeholder values with actual secrets):

```bash
# Development
kubectl create secret generic quest-logger-secrets \
  --namespace quest-logger-dev \
  --from-literal=DATABASE_URL="postgresql://user:pass@postgres:5432/db" \
  --from-literal=JWT_SECRET="your-jwt-secret" \
  --from-literal=RABBITMQ_USER="guest" \
  --from-literal=RABBITMQ_PASSWORD="guest" \
  --from-literal=REDIS_PASSWORD="redis-password"

# Production (use more secure values for production)
kubectl create secret generic quest-logger-secrets \
  --namespace quest-logger-prod \
  --from-literal=DATABASE_URL="postgresql://user:pass@postgres:5432/db" \
  --from-literal=JWT_SECRET="your-jwt-secret" \
  --from-literal=RABBITMQ_USER="guest" \
  --from-literal=RABBITMQ_PASSWORD="guest" \
  --from-literal=REDIS_PASSWORD="redis-password"
```

## Continuous Deployment

The Quest Logger application uses GitHub Actions for continuous deployment:

1. CI pipeline builds and pushes Docker images to GitHub Container Registry
2. CD pipeline deploys to development environment after successful CI
3. CD pipeline deploys to production environment after approval

To view pipeline status, check the Actions tab in the GitHub repository.

## Monitoring and Observability

After deployment, access the following services:

- **API**: Through the ingress URL (e.g., api.questlogger.com in production)
- **Prometheus**: Accessible via port-forward or internal service
- **Grafana**: Accessible via port-forward or internal service
- **Jaeger UI**: Accessible via port-forward or internal service

Example port forwarding for local access:

```bash
# Grafana
kubectl port-forward svc/grafana 3000:3000 -n monitoring

# Prometheus
kubectl port-forward svc/prometheus-server 9090:9090 -n monitoring

# Jaeger
kubectl port-forward svc/jaeger-query 16686:16686 -n observability
```

## Troubleshooting

Common issues and solutions:

1. **Pods not starting**: Check events with `kubectl describe pod <pod-name>`
2. **Service not accessible**: Verify service endpoints with `kubectl get endpoints`
3. **Persistent volume issues**: Check PVs and PVCs with `kubectl get pv,pvc`
4. **Configuration problems**: Verify ConfigMaps with `kubectl get configmap <name> -o yaml`
5. **Network connectivity**: Test with temporary debug pods `kubectl run busybox --image=busybox -it --rm -- sh`

For more detailed logs:

```bash
kubectl logs -f deployment/api-gateway -n quest-logger-dev
kubectl logs -f deployment/user-service -n quest-logger-dev
``` 