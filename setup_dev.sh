#!/bin/bash
set -e

export PYTHONPATH=$PYTHONPATH:$(pwd)
# Create a virtual environment
python -m venv venv


source venv/bin/activate

# Install the common package in development mode
pip install -e ./common

# Install service-specific dependencies for the service you're working on
pip install -r services/api-gateway/requirements.txt
pip install -r services/user-service/requirements.txt

# Install the service you're working on
pip install -e ./services/api-gateway
pip install -e ./services/user-service

