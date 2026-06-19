#!/bin/bash
# Auto-downloads the lca_methods database on first start if the volume is empty.
# This makes the gdt-server self-bootstrapping regardless of where the volume is mounted.
DB_DIR="/app/data/databases/lca_methods"
RELEASE_URL="https://github.com/calvinw/agentic-lca/releases/download/lca-data-v1/lca_methods-LCIA-methods-2.8.0-2026-06-18.tar.gz"

if [ ! -f "$DB_DIR/service.properties" ]; then
    echo "[olca] lca_methods database not found — downloading (~87 MB)..."
    mkdir -p /app/data/databases
    curl -L --progress-bar "$RELEASE_URL" -o /tmp/lca_methods.tar.gz
    tar -xzf /tmp/lca_methods.tar.gz -C /app/data/databases/
    rm /tmp/lca_methods.tar.gz
    echo "[olca] Database ready."
fi

exec /app/run.sh "$@"
