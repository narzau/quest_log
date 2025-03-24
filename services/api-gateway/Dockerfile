FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files first
COPY services/api-gateway/requirements.txt /app/api-gateway-requirements.txt
COPY common/requirements.txt /app/common-requirements.txt

# Install both sets of requirements 
RUN pip install --no-cache-dir -r /app/api-gateway-requirements.txt
RUN pip install --no-cache-dir -r /app/common-requirements.txt

# Copy common code
COPY common/ /app/common/

# Install common as editable package
RUN pip install --no-cache-dir -e ./common

# Copy service code
COPY services/api-gateway/ /app/services/api-gateway/

# Set environment variables
ENV PYTHONPATH=/app
ENV SERVICE_NAME=api-gateway
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory to service directory
WORKDIR /app/services/api-gateway

# Expose port
EXPOSE 8000

# Run the application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]