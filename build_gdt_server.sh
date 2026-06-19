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

echo "[gdt-server] Building image $IMAGE..."
docker build -t "$IMAGE" "$BUILD_DIR"

rm -rf "$BUILD_DIR"
echo "[gdt-server] Done. Image $IMAGE is ready."
docker images | grep gdt-server
