FROM python:3.11-slim

WORKDIR /app

# System deps: graphviz for SVG layout, curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Python deps — copy lockfile first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code
COPY sse_server.py lca_server.py lca_engine.py lca_svg_engine.py lca_svg.py ./
COPY case_studies/ ./case_studies/
COPY scripts/ ./scripts/

EXPOSE 9000
ENV PORT=9000
ENV BRIGHTWAY_PROJECT=lca_server
ENV BRIGHTWAY2_DIR=/app/brightway_data
ENV PATH="/app/.venv/bin:$PATH"

# Run setup (idempotent) then start server.
# Brightway data persists in /app/brightway_data via a Docker volume.
CMD ["sh", "-c", "python scripts/setup_databases.py && python sse_server.py"]
