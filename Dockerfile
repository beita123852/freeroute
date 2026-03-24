# ============================================
# FreeRoute - Multi-stage Docker Build
# ============================================

# --- Build stage ---
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime stage ---
FROM python:3.12-slim

# Labels
LABEL maintainer="beita123852"
LABEL description="FreeRoute - Free LLM API Aggregation Proxy"
LABEL version="0.1.0"

# Security: non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Set working directory
WORKDIR /app

# Copy application code (as root first)
COPY main.py .
COPY router.py .
COPY config.yaml .
COPY providers/ providers/
COPY utils/ utils/

# Patch config to bind 0.0.0.0 for Docker (must be done as root)
RUN sed -i 's/host: .*/host: 0.0.0.0/' config.yaml

# Create .env file if not exists (will be mounted in production)
RUN touch .env

# Fix permissions
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8090

# Health check - uses Python's urllib (no extra deps needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD /bin/sh -c 'python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8090/health\")"'

# Environment variables (can be overridden at runtime)
ENV FREEROUTE_API_KEY=""
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Start with uvicorn directly
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
