FROM python:3.11-slim

# Install system dependencies: cron for scheduled jobs, curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install python dependencies first to leverage Docker layer caching
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and MCP services into container
COPY app /app
COPY citizen_mcp /app/citizen_mcp
COPY officer_mcp /app/officer_mcp

# Create required upload and log directories
RUN mkdir -p /var/sewasetu/uploads /var/log/sewasetu \
    && crontab /app/deploy/crontab

# Set PYTHONPATH so both portal and MCP modules are discoverable
ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "30", "app:app"]
