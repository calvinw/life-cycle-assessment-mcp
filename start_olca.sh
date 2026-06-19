#!/usr/bin/env bash
# start_olca.sh
# Starts the openLCA gdt-server if it isn't already running.
#
# Usage:  bash start_olca.sh

IMAGE="gdt-server:latest"
CONTAINER="olca-server"
DATA_DIR="$HOME/olca-data"

mkdir -p "$DATA_DIR/databases"

# Skip if already running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[olca] Server is already running."
    exit 0
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

# Remove any stopped container with the same name
docker rm -f "$CONTAINER" 2>/dev/null || true

echo "[olca] Starting gdt-server on port 8080..."
docker run \
    --name "$CONTAINER" \
    --network host \
    -v "$DATA_DIR:/app/data" \
    -d \
    "$IMAGE" \
    -db lca_methods

for i in $(seq 1 15); do
    if curl -s http://localhost:8080/api/version > /dev/null 2>&1; then
        echo "[olca] Server ready at http://localhost:8080"
        exit 0
    fi
    sleep 2
done

echo "[olca] WARNING: Server may not be ready yet. Check: docker logs $CONTAINER"
