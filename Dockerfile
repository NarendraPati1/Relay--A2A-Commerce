# ─────────────────────────────────────────────
# Stage 1 – dependency builder
# ─────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install uv (fast pip replacement used by this project)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy only the dependency manifests so Docker caches this layer
COPY pyproject.toml uv.lock ./

# Install all runtime dependencies into a dedicated prefix
RUN uv pip install --system --no-cache \
    --python /usr/local/bin/python3 \
    -e . 2>/dev/null || \
    uv pip install --system --no-cache \
    --python /usr/local/bin/python3 \
    -r pyproject.toml


# ─────────────────────────────────────────────
# Stage 2 – slim runtime image
# ─────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Runtime env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PORT=8000

# curl is needed only for the HEALTHCHECK command
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed site-packages from the builder
COPY --from=builder /usr/local/lib/python3.13/site-packages \
                    /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source (frontend + backend)
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# The .env file is NOT copied – supply secrets at runtime via
# `docker run --env-file .env` or environment variables.

# Expose the buyer-agent HTTP port
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Buyer server auto-spawns merchant sub-processes at startup (lifespan).
# A2A_AUTO_START_MERCHANTS=true is the default; set false to manage
# merchant containers yourself via docker-compose.
CMD ["uvicorn", "agents.buyer.buyer_server:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
