@echo off
REM ============================================================================
REM One-shot migration: SQLite data.db  ->  PostgreSQL container
REM ============================================================================
REM Older deployments stored all application state in a single SQLite file at
REM data\data.db inside the mc-data volume. Current deployments use a
REM dedicated PostgreSQL container (see docker-compose.yml). This script
REM starts the postgres service, waits for it to be healthy, and runs the
REM Python migrator inside the mc-tool image.
REM
REM Run once after pulling the new code, BEFORE starting the rest of the
REM stack. Fresh installs do not need this script.
REM ============================================================================
setlocal

echo [migrate] Starting postgres service...
docker compose up -d postgres
if errorlevel 1 (
    echo [migrate] ERROR: failed to start postgres container.
    exit /b 1
)

echo [migrate] Waiting for postgres to become healthy...
set /a attempt=0
:wait_loop
set /a attempt+=1
docker compose exec -T postgres pg_isready -U mcserver -d mcserver >nul 2>&1
if not errorlevel 1 (
    echo [migrate] Postgres is ready.
    goto wait_done
)
if %attempt% geq 30 (
    echo [migrate] ERROR: postgres did not become ready within 30 seconds.
    docker compose logs postgres
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_loop
:wait_done

echo [migrate] Building / rebuilding mc-tool image...
REM --build ensures the image is rebuilt so it has the latest scripts\
REM and psycopg2-binary installed. Without this, an older cached image
REM may lack the migration script or the Postgres driver.
docker compose build mc-tool
if errorlevel 1 (
    echo [migrate] ERROR: failed to build mc-tool image.
    exit /b 1
)

echo [migrate] Running Python migrator inside the mc-tool image...
docker compose run --rm --no-deps mc-tool python scripts/migrate_sqlite_to_postgres.py
if errorlevel 1 (
    echo.
    echo [migrate] Migration FAILED.
    exit /b 1
)

echo.
echo [migrate] Migration complete.
echo   Backup:  the legacy data\data.db is still in the mc-data volume.
echo   Next:    build.cmd   (starts the full stack)

endlocal
