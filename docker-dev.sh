#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Show help message
show_help() {
  echo -e "${BLUE}Usage:${NC} $0 [command]"
  echo
  echo "Commands:"
  echo "  start         Start the development environment"
  echo "  stop          Stop the development environment"
  echo "  restart       Restart the development environment"
  echo "  logs [service] Show logs for all services or a specific service"
  echo "  ps            Show status of all containers"
  echo "  rebuild       Rebuild and restart services"
  echo "  clean         Stop and remove containers, networks, volumes, and images"
  echo "  shell [service] Open a shell in a running service container"
  echo "  cleanup-rabbitmq Clean up RabbitMQ resources (fixes connection issues)"
  echo "  help          Show this help message"
  echo
  echo "Examples:"
  echo "  $0 start                 # Start the entire environment"
  echo "  $0 logs api-gateway      # Show logs for api-gateway"
  echo "  $0 shell user-service    # Open shell in user-service container"
  echo "  $0 cleanup-rabbitmq      # Clean up stale RabbitMQ resources"
}

# Function to check if Docker Compose is installed
check_docker_compose() {
  if ! command -v docker compose &> /dev/null; then
    echo -e "${RED}Docker Compose is not installed.${NC}"
    echo "Please install Docker Compose to use this script."
    exit 1
  fi
}

# Function to check if required files exist
check_required_files() {
  echo -e "${BLUE}Checking for required files...${NC}"
  
  # Check for Docker Compose file
  if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}Error: docker-compose.yml not found!${NC}"
    exit 1
  fi
  
  # Check for .env file, create from example if not exists
  if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
      echo -e "${YELLOW}Creating .env from .env.example${NC}"
      cp .env.example .env
      echo -e "${YELLOW}Please review the .env file and set appropriate values.${NC}"
    else
      echo -e "${YELLOW}Warning: No .env or .env.example found.${NC}"
    fi
  fi
  
  # Check for API Gateway requirements
  if [ ! -f "services/api-gateway/requirements.txt" ]; then
    echo -e "${RED}Error: services/api-gateway/requirements.txt not found!${NC}"
    echo -e "Please create this file with the required dependencies for the API Gateway."
    exit 1
  fi
  
  # Check for User Service requirements
  if [ ! -f "services/user-service/requirements.txt" ]; then
    echo -e "${RED}Error: services/user-service/requirements.txt not found!${NC}"
    echo -e "Please create this file with the required dependencies for the User Service."
    exit 1
  fi
  
  echo -e "${GREEN}All required files found.${NC}"
}

# Function to start the development environment
start_env() {
  check_required_files
  echo -e "${BLUE}Starting development environment...${NC}"
  
  # Check if RabbitMQ config directory exists
  if [ ! -d "config/rabbitmq" ]; then
    echo -e "${YELLOW}RabbitMQ config directory not found. Creating it...${NC}"
    mkdir -p config/rabbitmq
    
    # Create basic RabbitMQ config if it doesn't exist
    if [ ! -f "config/rabbitmq/rabbitmq.conf" ]; then
      echo -e "${YELLOW}Creating basic RabbitMQ configuration...${NC}"
      cat > config/rabbitmq/rabbitmq.conf << EOF
# RabbitMQ Configuration File

# Memory threshold - when to start blocking producers
vm_memory_high_watermark.relative = 0.6

# Disk free space limit
disk_free_limit.absolute = 2GB

# Additional common settings
log.file.level = info
EOF
    fi
  fi
  
  docker compose up -d
  
  # Clean up RabbitMQ resources
  echo -e "${BLUE}Cleaning up RabbitMQ resources...${NC}"
  docker compose exec -T rabbitmq bash -c "/scripts/cleanup_rabbitmq.sh"
  
  echo -e "${GREEN}Development environment started.${NC}"
  echo -e "${BLUE}Services available at:${NC}"
  echo -e "API Gateway:       ${YELLOW}http://localhost:8000${NC}"
  echo -e "RabbitMQ Admin:    ${YELLOW}http://localhost:15672${NC} (guest/guest)"
  echo -e "Jaeger UI:         ${YELLOW}http://localhost:16686${NC}"
  echo -e "Prometheus:        ${YELLOW}http://localhost:9090${NC}"
  echo -e "Grafana:           ${YELLOW}http://localhost:3000${NC}"
  echo -e "Elasticsearch:     ${YELLOW}http://localhost:9200${NC}"
  echo -e "PostgreSQL:        ${YELLOW}localhost:5432${NC}"
  echo -e "Redis:             ${YELLOW}localhost:6379${NC}"
}

# Function to stop the development environment
stop_env() {
  echo -e "${BLUE}Stopping development environment...${NC}"
  docker compose down
  echo -e "${GREEN}Development environment stopped.${NC}"
}

# Function to restart the development environment
restart_env() {
  stop_env
  start_env
}

# Function to show logs
show_logs() {
  if [ $# -eq 0 ]; then
    echo -e "${BLUE}Showing logs for all services...${NC}"
    docker compose logs -f
  else
    echo -e "${BLUE}Showing logs for $1...${NC}"
    docker compose logs -f "$1"
  fi
}

# Function to show container status
show_status() {
  echo -e "${BLUE}Container status:${NC}"
  docker compose ps
}

# Function to rebuild services
rebuild_services() {
  echo -e "${BLUE}Rebuilding services...${NC}"
  docker compose down
  docker compose build
  docker compose up -d
  echo -e "${GREEN}Services rebuilt and restarted.${NC}"
}

# Function to clean everything
clean_env() {
  echo -e "${YELLOW}Warning: This will remove all containers, networks, volumes, and images related to this project.${NC}"
  read -p "Are you sure you want to continue? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Cleaning up development environment...${NC}"
    docker compose down -v --rmi all
    echo -e "${GREEN}Development environment cleaned.${NC}"
  fi
}

# Function to open a shell in a container
open_shell() {
  if [ $# -eq 0 ]; then
    echo -e "${RED}Error: Please specify a service name.${NC}"
    echo -e "Available services:"
    docker compose ps --services
    exit 1
  fi
  
  echo -e "${BLUE}Opening shell in $1 container...${NC}"
  docker compose exec "$1" /bin/sh || docker compose exec "$1" /bin/bash
}

# Function to clean up RabbitMQ
cleanup_rabbitmq() {
  echo -e "${BLUE}Cleaning up RabbitMQ resources...${NC}"
  docker compose exec -T rabbitmq bash -c "/scripts/cleanup_rabbitmq.sh"
  echo -e "${GREEN}RabbitMQ cleanup completed.${NC}"
}

# Check for Docker Compose
check_docker_compose

# Parse command
case "$1" in
  start)
    start_env
    ;;
  stop)
    stop_env
    ;;
  restart)
    restart_env
    ;;
  logs)
    show_logs "${@:2}"
    ;;
  ps)
    show_status
    ;;
  rebuild)
    rebuild_services
    ;;
  clean)
    clean_env
    ;;
  shell)
    open_shell "${@:2}"
    ;;
  cleanup-rabbitmq)
    cleanup_rabbitmq
    ;;
  help|--help|-h)
    show_help
    ;;
  *)
    echo -e "${RED}Unknown command: $1${NC}"
    show_help
    exit 1
    ;;
esac

exit 0 