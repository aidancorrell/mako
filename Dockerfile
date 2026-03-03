FROM python:3.12-slim AS builder

# Install uv for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* README.md ./
COPY src/ src/

# Install dependencies into the virtual environment
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.12-slim

# Create non-root user
RUN groupadd --gid 1000 mako && \
    useradd --uid 1000 --gid mako --shell /usr/sbin/nologin mako

# Install only the binaries we need for the shell tool allowlist
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment and app from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Ensure the venv python is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Workspace and data directories (mounted as volumes)
RUN mkdir -p /app/workspace /app/data && chown -R mako:mako /app/workspace /app/data

USER mako

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import mako; print('ok')" || exit 1

ENTRYPOINT ["python", "-m", "mako.main", "--telegram"]
