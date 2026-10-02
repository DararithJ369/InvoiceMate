# --- Stage 1: Build & Dependencies ---
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy project definition files
COPY pyproject.toml README.md ./

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code and scripts
COPY src/ ./src/
COPY main.py ./

# Install project package
RUN uv pip install --no-cache-dir .

# --- Stage 2: Final Runtime Container ---
FROM python:3.11-slim as runner

WORKDIR /app

# Install runtime dependencies (e.g. curl for health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment and app files from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY main.py pyproject.toml README.md ./

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR="/app/storage/invoices" \
    DATABASE_URL="sqlite:////app/data/invoicemate.db" \
    HOST="0.0.0.0" \
    PORT="8000"

# Create storage and database data directories
RUN mkdir -p /app/storage/invoices /app/data

EXPOSE 8000

# Copy startup entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
