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

echo "Source tree to migrate:"
ls -la ./data
echo
if [ -f "./data/data.db" ]; then
    echo "Found ./data/data.db ($(du -h ./data/data.db | cut -f1)) — will copy."
else
    echo "WARNING: ./data/data.db is missing; servers DB state will start empty."
fi
echo

echo "Stopping the stack..."
docker compose down || true

echo "Creating mc-data volume (no-op if it already exists)..."
docker volume create mc-data >/dev/null

echo "Copying ./data into mc-data (data.db, servers/, infrared/, caches) via alpine..."
docker run --rm \
    -v "$(pwd)/data:/src:ro" \
    -v mc-data:/dst \
    alpine \
    sh -c 'cp -a /src/. /dst/ && chown -R 1000:1000 /dst/servers 2>/dev/null || true'

echo
echo "Verifying volume contents:"
docker run --rm -v mc-data:/data alpine sh -c \
    'ls -la /data && echo && if [ -f /data/data.db ]; then echo "data.db present ($(du -h /data/data.db | cut -f1))."; else echo "ERROR: data.db missing from volume!"; exit 1; fi'

echo
echo "Migration complete."
echo "  Backup:  keep ./data around until you've confirmed servers start."
echo "  Remove:  once verified, 'rm -rf ./data' to reclaim disk."
echo
echo "Now rebuild and start the stack:"
echo "  ./build.sh"
