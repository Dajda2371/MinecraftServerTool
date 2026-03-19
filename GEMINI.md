# Project Overview

This project is a Python-based tool for managing Minecraft servers. It provides both a command-line interface (CLI) and a web interface to create, run, and interact with servers — all orchestrated via Docker containers with a Velocity proxy for hostname-based routing.

## Key Technologies

*   **Backend:** Python
*   **CLI:** Python `argparse` (in `cli.py`)
*   **Web Server:** Python's built-in `http.server` and `socketserver` (in `webserver.py`)
*   **API:** A simple REST-like API handled by a custom request handler in `api/handler.py`.
*   **Frontend:** HTML, CSS, and JavaScript (located in `api/get/ui/`)
*   **Proxy:** Velocity (Java-based Minecraft proxy for hostname routing)
*   **Containers:** Docker (management container + isolated child containers)
*   **Process Manager:** supervisord (runs webserver + Velocity inside management container)

## Architecture

The project uses a **management container + child containers** pattern:

### Management Container (`Dockerfile`, `docker-compose.yml`)
Runs two services via supervisord:
1.  **MinecraftServerTool** — Python web server + CLI for creating/managing servers
2.  **Velocity Proxy** — Routes player connections by hostname to the correct child container

The management container:
- Mounts `/var/run/docker.sock` to spawn/control child containers
- Exposes port **25565** (Velocity) and **8000** (web UI) to the host
- Connects to the `mc-net` Docker network

### Child Containers (spawned dynamically)
Each Minecraft server runs in its own isolated container:
- Based on `openjdk:21-jre-slim` (`Dockerfile.server`)
- Connected to `mc-net` only — **no published ports**
- Non-root `minecraft` user (UID 1000)
- Data persisted via bind mounts at `/data`
- `online-mode=false` (Velocity handles authentication)
- Velocity modern forwarding enabled

### Network Topology
```
Players → hostname:25565 → Velocity (management container)
                              ↓ mc-net (internal Docker network)
                    ┌─────────┼──────────┐
                    ↓         ↓          ↓
               server-a  server-b  server-c
               :25566    :25567    :25568
```

### Code Structure

1.  **`cli.py`:** CLI interface. Commands: server create/run/stop/delete/status/console, velocity start/stop/reload/status
2.  **`webserver.py`:** Web server. Initializes DB and Velocity config on startup.
3.  **`api/` directory:** Core logic:
    - `api/db.py` — SQLite database (servers, users, Velocity metadata)
    - `api/velocity.py` — Velocity proxy management (download, config, start/stop)
    - `api/post/server/` — Server CRUD: create, run, stop, delete, rebuild, owner
    - `api/get/server/` — Server console (RCON)
4.  **`Dockerfile`** — Management container image
5.  **`Dockerfile.server`** — Child server container image
6.  **`docker-compose.yml`** — Infrastructure definition (mc-net network, management container)
7.  **`supervisord.conf`** — Process manager config for management container

# Building and Running

## Running with Docker Compose (Recommended)

```bash
docker compose up -d --build
```

This starts the management container which:
- Runs the web UI on port 8000
- Runs Velocity proxy on port 25565
- Can spawn child server containers via Docker socket

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
*   **Velocity Routing:** All player traffic goes through Velocity on port 25565 with hostname-based routing.

# Server Creation

The `api/post/server/create.py` script handles the creation of new Minecraft servers.

## Supported Server Types

*   **Spigot:** Fully supported.
*   **Vanilla:** Not yet implemented.
*   **Paper:** Not yet implemented.

## Server Properties (auto-configured)

*   `online-mode=false` — Velocity handles Mojang authentication
*   Velocity modern forwarding enabled via `config/paper-global.yml`
*   Unique forwarding secret per server (stored in DB)
*   Hostname auto-generated as `{server_name}.mc.{DOMAIN}`

## Dependencies

*   **`wget`:** Required to download server files. Install: `brew install wget` (macOS) or `apt-get install wget` (Linux)
*   **Java 21+:** Required for Velocity and modern Minecraft versions.
*   **Docker:** Required for container management.

# DNS Setup

For production, each subdomain must point to the host IP:
```
survival.mc.example.com  → host IP
creative.mc.example.com  → host IP
skyblock.mc.example.com  → host IP
```

All connections use port **25565**. Velocity reads the hostname from the Minecraft handshake and routes accordingly.
