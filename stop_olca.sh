#!/usr/bin/env bash
# stop_olca.sh
# Stops the openLCA gdt-server if it is running.
#
# Usage:  bash stop_olca.sh

CONTAINER="olca-server"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[olca] Server is not running. Nothing to stop."
    exit 0
fi

echo "[olca] Stopping server..."
docker stop "$CONTAINER"
docker rm "$CONTAINER"
echo "[olca] Server stopped."
