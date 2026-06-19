#!/usr/bin/env bash
# start.sh — launch gdt-server, wait for ready, then start the MCP SSE server.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"

echo "[lca-mcp] Starting gdt-server..."
java -jar /app/gdt-server.jar -db lca_methods -data "$DATA_DIR" &

echo "[lca-mcp] Waiting for gdt-server to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/api/version > /dev/null 2>&1; then
        echo "[lca-mcp] gdt-server ready."
        break
    fi
    sleep 2
    echo "  ...waiting ($i/30)"
done

echo "[lca-mcp] Starting MCP SSE server on port ${PORT:-9000}..."
exec python3 sse_server.py
