# Multi-stage Dockerfile for AIEngine (Production-ready for GCP Cloud Run)

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install Cloud SQL Proxy (for GCP Cloud SQL connections)
RUN apt-get update && apt-get install -y \
    wget \
    && wget https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.2/cloud-sql-proxy.linux.amd64 -O /usr/local/bin/cloud-sql-proxy \
    && chmod +x /usr/local/bin/cloud-sql-proxy \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 aiengine && \
    chown -R aiengine:aiengine /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/aiengine/.local

# Make sure scripts in .local are usable
ENV PATH=/home/aiengine/.local/bin:$PATH

# Copy application code
COPY --chown=aiengine:aiengine . .

# Switch to non-root user
USER aiengine

# Expose port (Cloud Run uses PORT env var, defaults to 8000)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# Run database migrations and start application with gunicorn
# Cloud Run sets PORT environment variable
CMD ["sh", "-c", "alembic upgrade head && gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 300"]
