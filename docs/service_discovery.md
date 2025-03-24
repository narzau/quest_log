# Service Discovery

This document explains how service discovery works in the Quest Logger microservices architecture.

## Overview

The Quest Logger application uses Kubernetes native service discovery to allow services to find and communicate with each other dynamically.

## Kubernetes Service Discovery Implementation

### How It Works

1. **Kubernetes DNS**: 
   - Each service registered in Kubernetes automatically gets a DNS record
   - Services can be reached using consistent DNS names
   - The format is: `<service-name>.<namespace>.svc.cluster.local`
   - Within the same namespace, just `<service-name>` is sufficient

2. **Health Checking**:
   - Services are regularly checked for health via their `/health` endpoint
   - Unhealthy services are automatically detected

3. **Service Resolution**:
   - DNS resolution is used to convert service names to IP addresses
   - This happens transparently to your application code

### Implementation Details

Our implementation in `common/discovery.py` provides a clean, consistent interface for service discovery that's compatible with Kubernetes:

```python
# Example: Getting a service URL
service_url = await discover_service_url("user-service")

# Example: Using the service discovery decorator
@with_service_discovery("user-service")
async def call_user_service(service_url: str, user_id: str):
    # The service_url is automatically injected
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{service_url}/users/{user_id}") as response:
            return await response.json()
```

### Key Components

1. **KubernetesServiceRegistry**:
   - Main class responsible for service discovery using Kubernetes DNS
   - Provides methods for discovering services and checking health
   - Manages service state tracking

2. **ServiceDiscoveryMiddleware**:
   - Integrates with FastAPI to manage service registration/deregistration
   - Handles service lifecycle events during application startup/shutdown

3. **with_service_discovery Decorator**:
   - Injects service URLs into function calls
   - Simplifies service-to-service communication

## Local Development

For local development, we use a Minikube-based Kubernetes cluster:

1. Services are deployed to the `quest-logger-local` namespace
2. Service names have a `-local` suffix for clarity (e.g., `api-gateway-local`)
3. The custom Kubernetes overlay in `k8s/overlays/local` provides the configuration

## Environment Variables

The service discovery implementation uses these environment variables:

- `KUBERNETES_NAMESPACE`: The Kubernetes namespace for services (default: `default`)
- `POD_NAMESPACE`: Alternative way to specify the namespace
- `<SERVICE_NAME>_SERVICE_PORT`: The port for a specific service (default: `80`)

## Testing Service Discovery

You can test service discovery from any pod:

```bash
# Get a shell in a pod
kubectl exec -it <pod-name> -n quest-logger-local -- sh

# Test DNS resolution
nslookup user-service-local.quest-logger-local.svc.cluster.local

# Test HTTP connection
curl http://user-service-local/health
```

## Differences from Previous Implementation

The current implementation differs from the previous Consul-based implementation:

1. **No External Dependencies**: 
   - No longer requires a Consul server
   - Uses Kubernetes built-in features

2. **Simpler Configuration**:
   - No need to configure Consul connection details
   - Works automatically within Kubernetes

3. **DNS-based Discovery**:
   - Uses standard DNS resolution instead of Consul's HTTP API
   - More resilient and widely supported

4. **Native Integration**:
   - Better integration with Kubernetes environment
   - Leverages Kubernetes service health checks

The API remains backward compatible, so existing code should work without changes. 