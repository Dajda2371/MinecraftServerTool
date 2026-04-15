#!/bin/bash
# Entrypoint for child Minecraft server containers.
#
# /data is a Docker named volume (real Linux filesystem on every host,
# including Docker Desktop on macOS/Windows). chown works here, unlike
# the old host bind-mount layout where VirtioFS/WSL bind mounts silently
# ignored ownership changes and the Minecraft bundler would fail with
# AccessDenied when trying to create /data/versions.
#
# Start as root so we can set ownership, then drop privileges to the
# unprivileged minecraft user (UID 1000) before exec'ing Java.
set -e

chown -R 1000:1000 /data
exec gosu 1000:1000 "$@"
