#!/usr/bin/env bash
# ============================================================================
# One-shot migration: SQLite data.db  ->  PostgreSQL container
# ============================================================================
# Older deployments stored all application state in a single SQLite file at
# data/data.db inside the mc-data volume. Current deployments use a
# dedicated PostgreSQL container (see docker-compose.yml). This script
# starts the postgres service, waits for it to be healthy, and runs the
# Python migrator inside the mc-tool image.
#
# Run once after pulling the new code, BEFORE starting the rest of the
# stack. Fresh installs do not need this script.
# ============================================================================
set -euo pipefail

COMPOSE="docker compose"

echo "[migrate] Starting postgres service..."
$COMPOSE up -d postgres

echo "[migrate] Waiting for postgres to become healthy..."
# pg_isready exits 0 once the server accepts connections. Poll the
# container directly so we don't depend on compose health semantics that
# differ between versions.
for i in $(seq 1 30); do
    if $COMPOSE exec -T postgres pg_isready -U mcserver -d mcserver >/dev/null 2>&1; then
        echo "[migrate] Postgres is ready."
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "[migrate] ERROR: postgres did not become ready within 30 seconds." >&2
        $COMPOSE logs postgres | tail -n 50 >&2
        exit 1
    fi
done

echo "[migrate] Running Python migrator inside the mc-tool image..."
# --rm so we don't leave a stopped container behind; use `run` so the
# main mc-tool service isn't started yet (we migrate, then `./build.sh up`).
$COMPOSE run --rm --no-deps mc-tool python scripts/migrate_sqlite_to_postgres.py

echo
echo "[migrate] Migration complete."
echo "  Backup:  the legacy data/data.db is still in the mc-data volume."
echo "  Next:    ./build.sh up   (starts the full stack)"
