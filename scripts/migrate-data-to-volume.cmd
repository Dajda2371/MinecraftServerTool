@echo off
REM ============================================================================
REM One-shot migration: host .\data bind mount  ->  mc-data Docker volume
REM ============================================================================
REM Older deployments kept server files under .\data on the host and
REM bind-mounted that directory into the management and child containers.
REM That layout did not honour container-side chown on Docker Desktop
REM (Windows WSL2 /mnt/c), which broke the Minecraft bundler with
REM AccessDenied errors on server start.
REM
REM Current deployments put everything in the "mc-data" named volume. This
REM script copies an existing .\data tree into that volume. Run it once,
REM after pulling the new code and before `build.cmd`. Fresh installs do
REM not need it.
REM ============================================================================
setlocal

if not exist ".\data\" (
    echo No .\data directory found. Nothing to migrate -- just run build.cmd.
    exit /b 0
)

echo Stopping the stack...
docker compose down

echo Creating mc-data volume (no-op if it already exists)...
docker volume create mc-data >nul

echo Copying .\data into mc-data via an alpine helper container...
docker run --rm ^
    -v "%cd%\data:/src:ro" ^
    -v mc-data:/dst ^
    alpine ^
    sh -c "cp -a /src/. /dst/ && chown -R 1000:1000 /dst/servers 2>/dev/null || true"
if errorlevel 1 (
    echo.
    echo Migration FAILED. Leaving .\data in place.
    exit /b 1
)

echo.
echo Migration complete.
echo   Verify:  docker run --rm -v mc-data:/data alpine ls -la /data
echo   Backup:  keep .\data around until you've confirmed servers start.
echo   Remove:  once verified, rmdir /s /q data to reclaim disk.
echo.
echo Now rebuild and start the stack:
echo   build.cmd

endlocal
