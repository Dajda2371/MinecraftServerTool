#!/usr/bin/env bash
# ============================================================================
# One-shot migration: host ./data bind mount  →  mc-data Docker volume
# ============================================================================
# Older deployments kept server files under ./data on the host and
# bind-mounted that directory into the management and child containers.
# That layout didn't honour container-side chown on Docker Desktop
# (macOS VirtioFS, Windows WSL2 /mnt/c), which broke the Minecraft
# bundler with AccessDenied errors on server start.
#
# Current deployments put everything in the "mc-data" named volume. This
# script copies an existing ./data tree into that volume. Run it once,
# after pulling the new code and before `docker compose up`. Fresh
# installs do not need it.
# ============================================================================
set -euo pipefail

if [ ! -d "./data" ]; then
    echo "No ./data directory found. Nothing to migrate — just run the build."
    exit 0
fi

echo "Stopping the stack..."
docker compose down || true

echo "Creating mc-data volume (no-op if it already exists)..."
docker volume create mc-data >/dev/null

echo "Copying ./data into mc-data via an alpine helper container..."
docker run --rm \
    -v "$(pwd)/data:/src:ro" \
    -v mc-data:/dst \
    alpine \
    sh -c 'cp -a /src/. /dst/ && chown -R 1000:1000 /dst/servers 2>/dev/null || true'

echo
echo "Migration complete."
echo "  Verify:  docker run --rm -v mc-data:/data alpine ls -la /data"
echo "  Backup:  keep ./data around until you've confirmed servers start."
echo "  Remove:  once verified, 'rm -rf ./data' to reclaim disk."
echo
echo "Now rebuild and start the stack:"
echo "  ./build.sh"
