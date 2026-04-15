# Project Overview

This project is a Python-based tool for managing Minecraft servers. It provides both a command-line interface (CLI) and a web interface to create, run, and interact with servers — all orchestrated via Docker containers with an Infrared proxy for hostname-based routing.

## Key Technologies

*   **Backend:** Python
*   **CLI:** Python `argparse` (in `cli.py`)
*   **Web Server:** Python's built-in `http.server` and `socketserver` (in `webserver.py`)
*   **API:** A simple REST-like API handled by a custom request handler in `api/handler.py`.
*   **Frontend:** HTML, CSS, and JavaScript (located in `api/get/ui/`)
*   **Proxy:** Infrared (Go-based Minecraft reverse proxy, github.com/haveachin/infrared)
*   **Containers:** Docker (management container + proxy container + isolated child containers)
*   **Process Manager:** supervisord (runs the webserver inside the management container)

## Architecture

The project uses a **management container + proxy container + child containers** pattern:

### Management Container (`Dockerfile`, `docker-compose.yml` service `mc-tool`)
- Python web server + CLI for creating/managing servers
- Mounts `/var/run/docker.sock` to spawn/control child containers
- Generates Infrared config files into the shared `./data/infrared` volume
- Exposes port **8000** (web UI) to the host

### Proxy Container (`docker-compose.yml` service `infrared`)
- Runs `haveachin/infrared:latest`
- Exposes port **25565** to the host (the only Minecraft port)
- Reads config from `/etc/infrared` (mounted from `./data/infrared`)
- Watches config files and hot-reloads on changes — no restart required

### Child Containers (spawned dynamically)
Each Minecraft server runs in its own isolated container:
- Based on `eclipse-temurin:21-jre`
- Connected to `mc-net` only — **no published ports**
- Non-root user (UID 1000)
- Data persisted via bind mounts at `/data`
- `online-mode=true` — each backend handles its own Mojang authentication; Infrared only routes connections at the handshake level.

### Network Topology
```
Players → hostname:25565 → Infrared (mc-infrared container)
                              ↓ mc-net (internal Docker network)
                    ┌─────────┼──────────┐
                    ↓         ↓          ↓
               server-a  server-b  server-c
```

### Code Structure

1.  **`cli.py`:** CLI interface. Commands: server create/run/stop/delete/status/console, proxy start/stop/reload/status
2.  **`webserver.py`:** Web server. Initializes DB and Infrared config on startup.
3.  **`api/` directory:** Core logic:
    - `api/db.py` — SQLite database (servers, users)
    - `api/infrared.py` — Infrared proxy config generator (`config.yml` + per-server `proxies/*.yml`)
    - `api/post/server/` — Server CRUD: create, run, stop, delete, rebuild, owner
    - `api/get/server/` — Server console (RCON)
4.  **`Dockerfile`** — Management container image
5.  **`docker-compose.yml`** — Infrastructure definition (mc-net network, mc-tool + infrared services)
6.  **`supervisord.conf`** — Process manager config for management container

# Building and Running

## Running with Docker Compose (Recommended)

```bash
docker compose up -d --build
```

This starts:
- `mc-tool` — management web UI on port 8000
- `mc-infrared` — Infrared proxy on port 25565
- Child server containers are spawned on demand by `mc-tool` via the Docker socket

## Running the CLI (Development)

```bash
python3 cli.py
```

## Running the Web Server (Development)

```bash
python3 webserver.py
```

The web interface will be accessible at `http://localhost:8000`.

# Development Conventions

*   **Modularity:** The code is organized into modules based on functionality (CLI, web server, API).
*   **API Structure:** The `api` directory is structured by HTTP method (`get`, `post`) and then by resource (`server`, etc.).
*   **Frontend:** The frontend code is kept separate from the backend code in the `api/get/ui` directory.
*   **Docker Isolation:** Each Minecraft server runs in its own container with no direct host access.
*   **Infrared Routing:** All player traffic goes through Infrared on port 25565 with hostname-based routing. Infrared hot-reloads its config whenever `mc-tool` writes a new `proxies/*.yml` file.

# Server Creation

The `api/post/server/create.py` script handles the creation of new Minecraft servers.

## Supported Server Types

*   **Vanilla:** Supported (downloads official server JAR).
*   **Spigot:** Supported (built from source via BuildTools in a sidecar container).
*   **Paper:** Not yet implemented.

## Server Properties (auto-configured)

*   `online-mode=true` — each backend performs its own Mojang authentication
*   `server-port=25565` on the internal container IP (no host port published)
*   RCON enabled on port 25575 for console access
*   Hostname auto-generated as `{server_name}.mc.{DOMAIN}` and written as a `domains:` entry in `data/infrared/proxies/{server_name}.yml`

Unlike the previous Velocity-based setup, Infrared does NOT require a proxy plugin or `paper-global.yml` on the backend — it proxies at the Minecraft handshake level.

## Dependencies

*   **`wget`:** Required to download server files. Install: `brew install wget` (macOS) or `apt-get install wget` (Linux)
*   **Java 21+:** Required for modern Minecraft versions (inside the container).
*   **Docker:** Required for container management.
*   **SQLite 3.35+:** Required for the drop-column migration that retires the legacy `forwarding_secret` column (ships with any modern Linux distribution).

# DNS Setup

For production, each subdomain must point to the host IP:
```
survival.mc.example.com  → host IP
creative.mc.example.com  → host IP
skyblock.mc.example.com  → host IP
```

All connections use port **25565**. Infrared reads the hostname from the Minecraft handshake and routes accordingly.

# Migration Notes (Velocity → Infrared)

Servers created before this switch have `online-mode=false` in `server.properties` and a `config/paper-global.yml` with a Velocity forwarding secret. They continue to work under Infrared (Infrared just routes the connection), but:

- They accept offline-mode clients (any account/name), which is insecure.
- Their `paper-global.yml` is inert (no Velocity to talk to).

There is **no automatic migration** — existing servers keep their settings until they are recreated. To harden an existing server manually, edit its `data/servers/<name>/server.properties` to set `online-mode=true` and delete `data/servers/<name>/config/paper-global.yml`.
