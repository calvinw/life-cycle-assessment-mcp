#!/usr/bin/env bash
set -Eeuo pipefail

action=${1:?Missing action}
ref=${2:?Missing Git ref}
repo_url=${3:?Missing repository URL}
repo_dir=${4:?Missing repository directory}
container_name=${5:?Missing container name}
volume_name=${6:?Missing volume name}
image_name=${7:?Missing image name}
port_binding=${8:?Missing port binding}
health_url=${9:?Missing health URL}
rollback_name="${container_name}-rollback"

for command_name in curl docker flock git mktemp tar; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required server command is missing: $command_name" >&2
        exit 1
    fi
done

if [[ "$container_name" == *[!A-Za-z0-9_.-]* || -z "$container_name" ]]; then
    echo "Unsafe container name: $container_name" >&2
    exit 2
fi
if [[ "$volume_name" == *[!A-Za-z0-9_.-]* || -z "$volume_name" ]]; then
    echo "Unsafe volume name: $volume_name" >&2
    exit 2
fi
if [[ "$repo_dir" != /* || "$repo_dir" == "/" ]]; then
    echo "LCA_REMOTE_REPO_DIR must be a non-root absolute path." >&2
    exit 2
fi

exec 9>/var/lock/lca-server-deploy.lock
if ! flock -n 9; then
    echo "Another LCA deployment is already running." >&2
    exit 1
fi

container_exists() {
    docker container inspect "$1" >/dev/null 2>&1
}

wait_for_health() {
    local target=$1
    local attempt state
    for attempt in $(seq 1 120); do
        if ! container_exists "$target"; then
            return 1
        fi
        state=$(docker inspect --format '{{.State.Status}}' "$target")
        if [[ "$state" == "exited" || "$state" == "dead" ]]; then
            return 1
        fi
        if curl --fail --silent --show-error --max-time 3 "$health_url" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

show_failure_logs() {
    local target=$1
    echo "Last logs from $target:" >&2
    docker logs --tail 100 "$target" >&2 || true
}

rollback_failed_deploy() {
    if container_exists "$container_name"; then
        docker rm --force "$container_name" >/dev/null
    fi
    if container_exists "$rollback_name"; then
        docker rename "$rollback_name" "$container_name"
        docker start "$container_name" >/dev/null
        if wait_for_health "$container_name"; then
            echo "Previous container restored successfully." >&2
        else
            echo "WARNING: previous container was restarted but failed its health check." >&2
        fi
    fi
}

perform_rollback() {
    local displaced_name="${container_name}-displaced-$(date +%Y%m%d%H%M%S)"

    if ! container_exists "$rollback_name"; then
        echo "No rollback container is available." >&2
        exit 1
    fi
    if ! container_exists "$container_name"; then
        docker rename "$rollback_name" "$container_name"
        docker start "$container_name" >/dev/null
        wait_for_health "$container_name"
        echo "Rollback container started successfully."
        return
    fi

    docker stop --time 30 "$container_name" >/dev/null
    docker rename "$container_name" "$displaced_name"
    docker rename "$rollback_name" "$container_name"
    docker start "$container_name" >/dev/null

    if wait_for_health "$container_name"; then
        docker rename "$displaced_name" "$rollback_name"
        echo "Rollback completed. The displaced release is now the rollback target."
        return
    fi

    show_failure_logs "$container_name"
    docker stop --time 10 "$container_name" >/dev/null || true
    docker rename "$container_name" "${container_name}-failed-$(date +%Y%m%d%H%M%S)"
    docker rename "$displaced_name" "$container_name"
    docker start "$container_name" >/dev/null
    wait_for_health "$container_name" || true
    echo "Rollback target failed; the original deployment was restored." >&2
    exit 1
}

if [[ "$action" == "rollback" ]]; then
    perform_rollback
    exit 0
fi
if [[ "$action" != "deploy" ]]; then
    echo "Unknown deployment action: $action" >&2
    exit 2
fi

mkdir -p "$repo_dir"
if [[ ! -d "$repo_dir/.git" ]]; then
    if [[ -n $(find "$repo_dir" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
        echo "Repository directory exists but is not an empty Git checkout: $repo_dir" >&2
        exit 1
    fi
    git clone "$repo_url" "$repo_dir"
fi

git -C "$repo_dir" fetch --prune --tags origin

commit=""
if git -C "$repo_dir" rev-parse --verify --quiet \
    "refs/remotes/origin/${ref}^{commit}" >/dev/null; then
    commit=$(git -C "$repo_dir" rev-parse "refs/remotes/origin/${ref}^{commit}")
elif git -C "$repo_dir" rev-parse --verify --quiet \
    "refs/tags/${ref}^{commit}" >/dev/null; then
    commit=$(git -C "$repo_dir" rev-parse "refs/tags/${ref}^{commit}")
elif git -C "$repo_dir" rev-parse --verify --quiet "${ref}^{commit}" >/dev/null; then
    commit=$(git -C "$repo_dir" rev-parse "${ref}^{commit}")
else
    echo "Git ref is not available from the server checkout: $ref" >&2
    exit 1
fi

short_commit=$(git -C "$repo_dir" rev-parse --short=12 "$commit")
image_tag="${image_name}:${short_commit}"
build_dir=$(mktemp -d /tmp/lca-server-build.XXXXXX)
cleanup() {
    rm -rf "$build_dir"
}
trap cleanup EXIT

echo "Building commit $commit as $image_tag"
git -C "$repo_dir" archive "$commit" | tar -x -C "$build_dir"
docker build --pull \
    --label "com.mathplosion.lca.commit=$commit" \
    --tag "$image_tag" \
    "$build_dir"

docker volume inspect "$volume_name" >/dev/null 2>&1 \
    || docker volume create "$volume_name" >/dev/null

if container_exists "$rollback_name"; then
    docker rm --force "$rollback_name" >/dev/null
fi
if container_exists "$container_name"; then
    docker stop --time 30 "$container_name" >/dev/null
    docker rename "$container_name" "$rollback_name"
fi

if ! docker run --detach \
    --name "$container_name" \
    --restart unless-stopped \
    --publish "$port_binding" \
    --volume "${volume_name}:/app/brightway_data" \
    --env PORT=9000 \
    --env BRIGHTWAY_PROJECT=lca_server \
    --env BRIGHTWAY2_DIR=/app/brightway_data \
    --health-cmd 'curl -fsS http://127.0.0.1:9000/api/health >/dev/null || exit 1' \
    --health-interval 15s \
    --health-timeout 5s \
    --health-retries 5 \
    --health-start-period 180s \
    --label "com.mathplosion.lca.commit=$commit" \
    "$image_tag" >/dev/null; then
    echo "New container could not be created; restoring the previous release." >&2
    rollback_failed_deploy
    exit 1
fi

echo "Waiting for $health_url"
if ! wait_for_health "$container_name"; then
    show_failure_logs "$container_name"
    echo "New release failed its health check; restoring the previous release." >&2
    rollback_failed_deploy
    exit 1
fi

echo "Deployment succeeded."
echo "Commit: $commit"
echo "Image:  $image_tag"
echo "URL:    https://lca.mathplosion.com"
if container_exists "$rollback_name"; then
    echo "Rollback: scripts/deploy_lca_server.sh --rollback"
fi
