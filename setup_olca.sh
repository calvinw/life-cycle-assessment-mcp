#!/usr/bin/env bash
# setup_olca.sh
# Builds (if needed) and starts the openLCA gdt-server Docker container.
# Run this once at the start of a Codespaces session.
#
# Usage:  bash setup_olca.sh
# The server will be available at http://localhost:8080

set -e

IMAGE="gdt-server:latest"
CONTAINER="olca-server"
DATA_DIR="$HOME/olca-data"
RELEASE_BASE="https://github.com/calvinw/agentic-lca/releases/download/lca-data-v1"
LCA_COMMONS_DB="$DATA_DIR/databases/lca_methods"

mkdir -p "$DATA_DIR/databases"

# Download and unzip the pre-built lca_methods database if not already present.
# This database includes all 45 LCIA methods (TRACI 2.2, ReCiPe 2016, EF 3.1, etc.)
# already imported — no slow import step needed.
if [ ! -d "$LCA_COMMONS_DB" ]; then
    echo "[olca] Downloading lca_methods database (87 MB)..."
    curl -L --progress-bar "$RELEASE_BASE/lca_methods-LCIA-methods-2.8.0-2026-06-18.tar.gz" \
        -o "$DATA_DIR/lca_methods.tar.gz"
    echo "[olca] Extracting lca_methods database..."
    tar -xzf "$DATA_DIR/lca_methods.tar.gz" -C "$DATA_DIR/databases/"
    rm "$DATA_DIR/lca_methods.tar.gz"
    echo "[olca] Database ready."
else
    echo "[olca] lca_methods database already present — skipping download."
fi

# Build the image if it doesn't exist yet
if ! docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "[olca] Building gdt-server image (this only happens once)..."
    BUILD_DIR=$(mktemp -d)
    curl -fsSL https://raw.githubusercontent.com/GreenDelta/gdt-server/main/Dockerfile \
        -o "$BUILD_DIR/Dockerfile.upstream"
    sed 's|eclipse-temurin:21-jre|eclipse-temurin:17-jre|' \
        "$BUILD_DIR/Dockerfile.upstream" > "$BUILD_DIR/Dockerfile"
    docker build -t "$IMAGE" "$BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi

echo "[olca] Setup complete. gdt-server image and database are ready."
echo "[olca] Deploy via Coolify docker-compose to start the server."
