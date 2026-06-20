FROM python:3.11-slim

WORKDIR /app

# System deps: graphviz for SVG layout
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps (brightway25 is the heaviest — install first for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY sse_server.py lca_server.py lca_engine.py lca_svg_engine.py lca_svg.py ./
COPY case_studies/ ./case_studies/
COPY data/ ./data/
COPY scripts/ ./scripts/

EXPOSE 9000
ENV PORT=9000
ENV BRIGHTWAY_PROJECT=lca_server

# Run setup (idempotent) then start server.
# Brightway data persists in /app/brightway_data via a Docker volume.
ENV BRIGHTWAY_DIR=/app/brightway_data
CMD ["sh", "-c", "python scripts/setup_databases.py && python sse_server.py"]
