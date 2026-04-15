@echo off
docker compose --profile build-only build mc-server-base
docker compose up -d --build
