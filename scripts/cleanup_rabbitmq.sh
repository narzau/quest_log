#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting RabbitMQ cleanup...${NC}"

# Set default values
RABBITMQ_HOST=${RABBITMQ_HOST:-rabbitmq}
RABBITMQ_USER=${RABBITMQ_USER:-guest}
RABBITMQ_PASS=${RABBITMQ_PASS:-guest}
RABBITMQ_PORT=${RABBITMQ_PORT:-15672}

# Install dependencies if they don't exist
if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  echo -e "${YELLOW}Installing required dependencies...${NC}"
  
  # Detect the package manager (Alpine uses apk, Debian/Ubuntu uses apt-get)
  if command -v apk >/dev/null 2>&1; then
    apk update && apk add --no-cache curl jq
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y curl jq
  else
    echo -e "${RED}Could not install dependencies. Make sure curl and jq are installed.${NC}"
    exit 1
  fi
fi

# Wait for RabbitMQ to be ready
echo -e "${BLUE}Waiting for RabbitMQ to be ready...${NC}"
until curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/vhosts" >/dev/null; do
  echo -e "${YELLOW}RabbitMQ is not ready yet...${NC}"
  sleep 2
done

echo -e "${GREEN}RabbitMQ is ready.${NC}"

# Step 1: Delete ALL callback queues
echo -e "${BLUE}Cleaning up ALL callback queues...${NC}"
CALLBACK_QUEUES=$(curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/queues" | jq -r '.[] | select(.name | contains("callback")) | .name')

if [ -z "$CALLBACK_QUEUES" ]; then
  echo -e "${GREEN}No callback queues found.${NC}"
else
  echo -e "${YELLOW}Found callback queues. Deleting...${NC}"
  for QUEUE in $CALLBACK_QUEUES; do
    echo -e "Deleting queue: $QUEUE"
    curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" -X DELETE "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/queues/%2F/$QUEUE"
  done
  echo -e "${GREEN}Callback queues deleted.${NC}"
fi

# Step 2: Find and delete ANY queues with resource_locked errors
echo -e "${BLUE}Checking for locked queues...${NC}"
ALL_QUEUES=$(curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/queues" | jq -r '.[].name')
LOCKED_QUEUES=""

for QUEUE in $ALL_QUEUES; do
  # Try to access the queue - if it returns a 405 status, it's likely locked
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -u "$RABBITMQ_USER:$RABBITMQ_PASS" -X GET "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/queues/%2F/$QUEUE/get" -H "Content-Type: application/json" -d '{"count":1,"requeue":true,"encoding":"auto","truncate":50000}')
  
  if [ "$STATUS" -eq 405 ]; then
    LOCKED_QUEUES="$LOCKED_QUEUES $QUEUE"
  fi
done

if [ -z "$LOCKED_QUEUES" ]; then
  echo -e "${GREEN}No locked queues found.${NC}"
else
  echo -e "${YELLOW}Found locked queues. Deleting...${NC}"
  for QUEUE in $LOCKED_QUEUES; do
    echo -e "Deleting locked queue: $QUEUE"
    curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" -X DELETE "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/queues/%2F/$QUEUE"
  done
  echo -e "${GREEN}Locked queues deleted.${NC}"
fi

# Step 3: Force close any lingering connections
echo -e "${BLUE}Checking for lingering connections...${NC}"
CONNECTIONS=$(curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/connections" | jq -r '.[].name')

if [ -z "$CONNECTIONS" ]; then
  echo -e "${GREEN}No lingering connections found.${NC}"
else
  echo -e "${YELLOW}Found lingering connections. Closing...${NC}"
  for CONN in $CONNECTIONS; do
    echo -e "Closing connection: $CONN"
    curl -s -u "$RABBITMQ_USER:$RABBITMQ_PASS" -X DELETE "http://$RABBITMQ_HOST:$RABBITMQ_PORT/api/connections/$CONN"
  done
  echo -e "${GREEN}Lingering connections closed.${NC}"
fi

echo -e "${GREEN}RabbitMQ cleanup completed successfully.${NC}"
exit 0 