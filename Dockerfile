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

# Create non-root user (override UID/GID to match host user for volume permissions)
ARG MAKO_UID=1000
ARG MAKO_GID=1000
RUN groupadd --gid ${MAKO_GID} mako && \
    useradd --uid ${MAKO_UID} --gid mako --shell /usr/sbin/nologin mako

# No extra binaries needed — default shell allowlist is "date" only.
# The web_fetch tool handles URL fetching with SSRF protections.

WORKDIR /app

# Copy the virtual environment and app from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Ensure the venv python is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Workspace and data directories (mounted as volumes)
RUN mkdir -p /app/workspace /app/data /app/audit && chown -R mako:mako /app/workspace /app/data /app/audit

USER mako

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import mako; print('ok')" || exit 1

ENTRYPOINT ["python", "-m", "mako.main", "--telegram"]
