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

# Configuration (environment variables)

The image is configured entirely through environment variables so the same
build runs under plain Compose, the GitHub-Release `deploy.sh` flow, and Coolify
(`deploy/docker-compose.coolify.yml`, guide in `deploy/COOLIFY.md`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | `postgres`/`5432`/`mcserver`/`mcserver`/`mcserver` | Database connection (`api/db.py`) |
| `SERVER_BASE_IMAGE` | `mc-server-base:latest` | Image for spawned Minecraft containers; pre-pulled at startup |
| `MC_DOMAIN` | – | Auto hostnames become `<server>.mc.<MC_DOMAIN>` (`api/post/server/create.py`) |
| `MC_SUBDOMAIN` | – | Full override of the hostname suffix (takes precedence over `MC_DOMAIN`) |
| `MC_DOCKER_NETWORK` | `mc-net` | Network joined by spawned containers (`api/post/server/run.py`) |
| `INFRARED_CONTAINER` | – | Explicit Infrared container name; otherwise found via compose labels (`api/infrared.py`) |
| `MC_JAVA_VERSION` | – (auto) | Force one bundled Java runtime (17, 21 or 25) for every server; default picks per Minecraft version |
| `MC_REAL_IP` | `1` | `0` disables the real-player-IP helper (go-mmproxy) for newly started servers |
| `MC_REAL_IP_PROXY_PORT` | `25566` | Port go-mmproxy listens on inside each server container |
| `EXTERNAL_HTTPS_PROXY` | – | `true` disables the in-app nginx/certbot HTTPS feature (TLS handled by the platform proxy) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Read by uvicorn; set `*` behind a trusted reverse proxy |

The management container never relies on fixed sibling container names: it
inspects its own container (`api/post/server/mounts.py`) to learn the real data
volume name and compose project, and locates the `infrared` service by labels.
Orchestrators that rename containers/volumes (Coolify) therefore work unchanged.
`GET /healthz` is an unauthenticated health endpoint for container healthchecks.

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

## World Import / Export (`api/post/server/world.py`)

*   **Create from a single-player world:** the Create Server modal accepts an optional `.zip` of a save folder (the one containing `level.dat`). `POST /api/server/create-from-world` streams it to `data/servers/<name>/.world-import.zip`, validates it, and the normal creation thread extracts it into `world/` after the jar is downloaded/built. The archive is always extracted in the **vanilla layout** (`world/DIM-1`, `world/DIM1`); Spigot/Paper migrate that into `world_nether` / `world_the_end` themselves on first boot, so it must not be pre-split.
*   **Download as a single-player world:** Settings → *Download World* calls `POST /api/server/<name>/world/export` (builds `data/servers/<name>/.exports/<token>.zip`, rejected with 409 while the server is running) and then navigates to `GET /api/server/<name>/world/export/<token>`, which serves the file and deletes it. For Bukkit-type servers `<level>_nether/DIM-1` and `<level>_the_end/DIM1` are folded back under the top-level `<name>/` folder so the client finds them.
*   Both paths write directly to `data/servers/<name>/` (like the file explorer uploads), so they require `mc-tool` to run inside Docker with `mc-data` mounted at `/app/data`.
*   The nginx templates in `api/https.py` set `client_max_body_size 0` and 900 s proxy timeouts so large worlds pass through the HTTPS proxy.

## Dependencies

*   **`wget`:** Required to download server files. Install: `brew install wget` (macOS) or `apt-get install wget` (Linux)
*   **Java:** 17, 21 and 25 are bundled in the server base image and selected per server version.
*   **Docker:** Required for container management.
*   **SQLite 3.35+:** Required for the drop-column migration that retires the legacy `forwarding_secret` column (ships with any modern Linux distribution).

# Java Runtime per Server

The base image bundles Java 8, 16, 17, 21 and 25 (`/opt/java/jdk<N>`).
Each server has a `java_runtime` selector in the database (`auto`,
`bundled:<N>` or `custom:<id>`), editable under Settings → Java Runtime.
`run.py` (`resolve_java_runtime`) turns it into `JAVA_VERSION` for the
container; `auto` maps the Minecraft version (the leading `X.Y.Z` of the stored
version, also for `mc-loader` Forge/NeoForge strings):

| Minecraft | Java |
| --- | --- |
| 26.1 and later (year-based releases) | 25 |
| 1.20.5 – 1.21.x | 21 (Spigot 1.21 refuses anything above 23) |
| 1.18 – 1.20.4 | 17 |
| 1.17 – 1.17.1 | 16 |
| 1.12 – 1.16.5 (and older) | 8 |

The entrypoint puts the chosen runtime on `PATH` and logs it. Unknown
`JAVA_VERSION` values fall back to the image default (25).

## Custom runtimes (`api/java_runtimes.py`)

Admins can add any other version/vendor under Admin → Java Runtimes:

* **Catalog** — every major version of every maintained distribution (Temurin,
  Zulu, Corretto, Liberica, Microsoft, GraalVM, SapMachine, …) via the foojay
  Disco API (`https://api.foojay.io/disco/v3.0`), filtered to Linux builds for
  the host architecture (`docker info` → `x64` / `aarch64`). JRE packages are
  preferred over JDKs.
* **URL** — a direct link to a `.tar.gz` / `.tgz` / `.tar` / `.zip` archive.
* **Upload** — the same kind of archive uploaded through the panel.

Install jobs run in a background thread: download → safe extract (path
traversal rejected) → locate the directory containing `bin/java` → move it to
`data/.java/<id>/home` → fix permissions → verify with `java -version` in a
throwaway container of the server base image (as UID 1000). Status
(`downloading` / `extracting` / `verifying` / `ready` / `failed`) and the
detected version are stored in the `java_runtimes` table. A `custom:<id>`
selector mounts `data/.java/<id>/home` read-only at `/opt/java/custom` and sets
`JAVA_VERSION=custom`; if the runtime is missing or not ready the server falls
back to `auto`. Runtimes still selected by a server cannot be deleted.

# Real Player IPs (PROXY protocol + go-mmproxy)

Infrared is a TCP proxy, so on its own every server would see players as the
Infrared container's address. To fix this for **every server type** without
plugins or mods, the base image (`Dockerfile.server`) ships
[go-mmproxy](https://github.com/path-network/go-mmproxy):

1. `run.py` starts server containers with `CAP_NET_ADMIN`, `MMPROXY_PORT` and
   the label `mc.real-ip.port=25566` — only if the image carries the label
   `mc-server-base.real-ip=true` (older base images keep the old behaviour).
2. `docker/server-entrypoint.sh` installs loopback policy routing
   (`ip rule add from 127.0.0.1/8 iif lo table 123` / `ip route add local
   0.0.0.0/0 dev lo table 123`) and runs
   `go-mmproxy -l 0.0.0.0:25566 -4 127.0.0.1:<server-port>` before dropping
   to UID 1000 and exec'ing Java. If the capability is missing it logs a
   warning and runs without the helper.
3. `api/infrared.py` checks the container label and writes
   `addresses: [mc-<name>:25566]` + `sendProxyProtocol: true` for such
   servers; others get the plain `mc-<name>:25565` route without a header.

go-mmproxy strips the PROXY header and connects to Java from the player's IP
(IP_TRANSPARENT), so logs, bans and plugins see the real address. Direct
connections through per-server published ports (firewall rules) still hit the
server port without a header and keep working.

Upgrading: servers started before this change keep the old route until they
are stopped and started again from the panel (the container is recreated from
the new base image with the capability and label).

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
