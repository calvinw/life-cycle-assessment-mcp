#!/usr/bin/env bash
# build_gdt_server.sh
# Builds the gdt-server Docker image on the host.
# Run this once on the Droplet before deploying with Coolify.

set -e

IMAGE="gdt-server:latest"

echo "[gdt-server] Creating build directory..."
BUILD_DIR=$(mktemp -d)

echo "[gdt-server] Downloading Dockerfile..."
curl -fsSL "https://raw.githubusercontent.com/GreenDelta/gdt-server/main/Dockerfile" \
    -o "$BUILD_DIR/Dockerfile.upstream"

echo "[gdt-server] Patching JRE version (21 -> 17)..."
sed 's|eclipse-temurin:21-jre|eclipse-temurin:17-jre|' \
    "$BUILD_DIR/Dockerfile.upstream" > "$BUILD_DIR/Dockerfile"

echo "[gdt-server] Adding bootstrap entrypoint..."
curl -fsSL "https://raw.githubusercontent.com/calvinw/life-cycle-assessment-mcp/main/gdt_entrypoint.sh" \
    -o "$BUILD_DIR/gdt_entrypoint.sh"

cat >> "$BUILD_DIR/Dockerfile" << 'EOF'

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY gdt_entrypoint.sh /gdt_entrypoint.sh
RUN chmod +x /gdt_entrypoint.sh
ENTRYPOINT ["/gdt_entrypoint.sh"]
EOF

echo "[gdt-server] Building image $IMAGE..."
docker build -t "$IMAGE" "$BUILD_DIR"

rm -rf "$BUILD_DIR"
echo "[gdt-server] Done. Image $IMAGE is ready."
docker images | grep gdt-server
