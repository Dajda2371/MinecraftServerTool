#!/usr/bin/env bash
# Pull the published images and (re)start the MinecraftServerTool stack.
# Expects docker-compose.yml (the repo's root compose file, attached to every
# GitHub Release) and an optional .env next to this script.
# Re-run this any time to deploy a new release.
set -euo pipefail
cd "$(dirname "$0")"

# Pick up VERSION/POSTGRES_PASSWORD from .env. They are used both by
# docker-compose.yml (image tags) and by the explicit docker pull below.
set -a; [ -f .env ] && . ./.env; set +a
VERSION="${VERSION:-latest}"
export VERSION

echo ">> Deploying version: ${VERSION}"

echo ">> Pulling compose service images (mc-tool, postgres, infrared)..."
docker compose pull

echo ">> Pulling spawned-server base image (used by mc-tool to launch servers)..."
docker pull "ghcr.io/dajda2371/mc-server-base:${VERSION}"

echo ">> Starting stack..."
docker compose up -d --no-build

echo ">> Status:"
docker compose ps
