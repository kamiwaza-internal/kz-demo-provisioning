FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install additional dependencies for provisioning
RUN pip install --no-cache-dir httpx pyyaml

# Copy application code
COPY app/ ./app/
COPY worker/ ./worker/
COPY terraform/ ./terraform/

# Create necessary directories
RUN mkdir -p uploads jobs_workdir

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command - run web server
# Note: In production, you'd typically run both web server and worker,
# or run them as separate containers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
