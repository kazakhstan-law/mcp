#!/usr/bin/env bash
# Rebuild and restart the server when the image does not run the checkout's HEAD.
#   scripts/deploy.sh           deploy HEAD if it is not what runs
#   scripts/deploy.sh --force   rebuild even if it is
# Tests run first (the Dockerfile's test stage); a new image that fails its health check is
# rolled back to the previous one. On latitude the post-merge hook runs this after
# fleet-selfpull fast-forwards main: deploy/hooks/post-merge.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=kazakhstan-law-mcp:local
PREV=kazakhstan-law-mcp:prev

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/kzlaw-deploy.lock"
flock -n 9 || { echo "another deploy is running"; exit 0; }

rev="$(git rev-parse HEAD)"
running="$(docker image inspect "$IMAGE" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)"
if [ "$running" = "$rev" ] && [ "${1:-}" != --force ]; then
  echo "up to date at ${rev:0:7}"
  exit 0
fi
echo "deploying ${rev:0:7} (running: ${running:-none})"

docker build --target test --quiet . >/dev/null
docker image inspect "$IMAGE" >/dev/null 2>&1 && docker image tag "$IMAGE" "$PREV"
docker compose build --build-arg REVISION="$rev"
docker compose up -d

healthy() {
  for _ in $(seq 30); do
    if docker compose exec -T server python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

if healthy; then
  echo "deployed ${rev:0:7}"
  exit 0
fi
echo "health check failed: rolling back to the previous image" >&2
if docker image inspect "$PREV" >/dev/null 2>&1; then
  docker image tag "$PREV" "$IMAGE"
  docker compose up -d --force-recreate
fi
exit 1
