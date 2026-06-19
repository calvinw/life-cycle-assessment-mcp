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

echo "[olca] Installing required Python packages..."
pip install olca-ipc olca-schema pyyaml numpy matplotlib --break-system-packages -q
echo "[olca] Python packages ready."

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

# Stop and remove any existing container with the same name
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[olca] Removing existing container: $CONTAINER"
    docker rm -f "$CONTAINER"
fi

echo "[olca] Starting gdt-server on port 8080..."
docker run \
    --name "$CONTAINER" \
    --network host \
    -v "$DATA_DIR:/app/data" \
    -d \
    "$IMAGE" \
    -db lca_methods

echo "[olca] Waiting for server to start..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8080/api/version > /dev/null 2>&1; then
        echo "[olca] Server ready at http://localhost:8080"
        curl -s http://localhost:8080/api/version
        echo ""

        exit 0
    fi
    sleep 2
    echo "  ...waiting ($i/30)"
done

echo "ERROR: Server did not start in time. Check Docker logs:"
echo "  docker logs $CONTAINER"
exit 1
