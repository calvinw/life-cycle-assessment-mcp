#!/usr/bin/env bash
# start_olca_ecoinvent.sh
# Starts the openLCA gdt-server pointed at an ecoinvent database.
#
# REQUIREMENTS:
#   1. You must have an ecoinvent license (ecoinvent.org).
#   2. The pre-built database is stored in a private GitHub repository:
#        calvinw/ecoinvent-lca-db  →  release tag: lca-data-v1  →  ecoinvent.zip
#   3. You must be logged in to the GitHub CLI before running this script:
#        gh auth login
#   4. Run setup_olca.sh first to build the gdt-server Docker image.
#
# If the ecoinvent database folder is already present, the download is skipped.
# To switch back to the free lca_methods database:  bash start_olca.sh

set -e

IMAGE="gdt-server:latest"
CONTAINER="olca-server"
DATA_DIR="$HOME/olca-data"
ECOINVENT_DB="$DATA_DIR/databases/ecoinvent"
ECOINVENT_ZIP="$DATA_DIR/ecoinvent.zip"
PRIVATE_REPO="calvinw/ecoinvent-lca-db"
RELEASE_TAG="lca-data-v1"

mkdir -p "$DATA_DIR/databases"

# ── Prerequisites ─────────────────────────────────────────────────────────────

if ! docker image inspect "$IMAGE" > /dev/null 2>&1; then
    echo "[olca] gdt-server image not found. Run setup_olca.sh first to build it."
    exit 1
fi

# ── Download ecoinvent database if not present ────────────────────────────────

if [ ! -d "$ECOINVENT_DB" ]; then
    echo "[olca] ecoinvent database not found — downloading from private repository..."

    # Check gh CLI is available and authenticated
    if ! command -v gh > /dev/null 2>&1; then
        echo "[olca] ERROR: GitHub CLI (gh) is not installed."
        echo "[olca] Install it with:  sudo apt install gh"
        exit 1
    fi

    if ! gh auth status > /dev/null 2>&1; then
        echo "[olca] ERROR: Not logged in to GitHub."
        echo "[olca] Log in first with:  gh auth login"
        echo "[olca] Then re-run this script."
        exit 1
    fi

    echo "[olca] Downloading ecoinvent.zip from $PRIVATE_REPO (requires ecoinvent license)..."
    gh release download "$RELEASE_TAG" \
        --repo "$PRIVATE_REPO" \
        --pattern "ecoinvent.zip" \
        --output "$ECOINVENT_ZIP"

    echo "[olca] Unzipping database..."
    mkdir -p "$ECOINVENT_DB"
    unzip -q "$ECOINVENT_ZIP" -d "$ECOINVENT_DB"
    rm -f "$ECOINVENT_ZIP"
    echo "[olca] ecoinvent database ready at $ECOINVENT_DB"
else
    echo "[olca] ecoinvent database already present — skipping download."
fi

# ── Stop any running container ────────────────────────────────────────────────

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[olca] Removing existing container: $CONTAINER"
    docker rm -f "$CONTAINER"
fi

# ── Start server ──────────────────────────────────────────────────────────────

echo "[olca] Starting gdt-server with ecoinvent database on port 8080..."
docker run \
    --name "$CONTAINER" \
    --network host \
    -v "$DATA_DIR:/app/data" \
    -d \
    "$IMAGE" \
    -db ecoinvent

echo "[olca] Waiting for server to start..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8080/api/version > /dev/null 2>&1; then
        echo "[olca] Server ready at http://localhost:8080 (ecoinvent)"
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
