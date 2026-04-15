# ============================================================================
# Management Container Dockerfile
# ============================================================================
# This container runs the MinecraftServerTool (Python web server + CLI for
# managing Minecraft servers). It generates Infrared proxy config and spawns
# child server containers via the Docker socket.
#
# Infrared runs in a separate container (see docker-compose.yml).
# ============================================================================

FROM python:3.13-bookworm

# ---- System Dependencies ----
RUN apt-get update && apt-get install -y \
    wget \
    screen \
    procps \
    curl \
    supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---- Docker CLI (to control sibling containers via mounted socket) ----
RUN curl -fsSL https://get.docker.com | sh

# ---- Application Setup ----
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Ensure data directories exist
RUN mkdir -p data/servers data/infrared data/infrared/proxies

# ---- Supervisor Configuration ----
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# ---- Ports ----
# 8000 = Web management interface
EXPOSE 8000

# ---- Entrypoint ----
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
