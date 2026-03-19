# ============================================================================
# Management Container Dockerfile
# ============================================================================
# This container runs TWO services:
#   1. The MinecraftServerTool (Python web server + CLI for managing servers)
#   2. Velocity proxy (Java-based, routes player connections by hostname)
#
# It also needs Docker CLI access to spawn child server containers.
# ============================================================================

FROM python:3.13-slim-bookworm

# ---- System Dependencies ----
RUN apt-get update && apt-get install -y \
    wget \
    git \
    screen \
    procps \
    curl \
    supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---- Docker CLI (to control sibling containers via mounted socket) ----
RUN curl -fsSL https://get.docker.com | sh

# ---- Java for Velocity proxy + BuildTools ----
# Install OpenJDK 21 from Adoptium (stable, works for Velocity and MC 1.20.4+)
RUN mkdir -p /usr/lib/jvm && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then \
        JDK_ARCH="aarch64"; \
    else \
        JDK_ARCH="x64"; \
    fi && \
    wget -q "https://api.adoptium.net/v3/binary/latest/21/ga/linux/${JDK_ARCH}/jdk/hotspot/normal/eclipse" -O /tmp/jdk.tar.gz && \
    tar -xzf /tmp/jdk.tar.gz -C /usr/lib/jvm && \
    rm /tmp/jdk.tar.gz

# Set JAVA_HOME and add to PATH
RUN export JAVA_HOME=$(ls -d /usr/lib/jvm/jdk-21*) && \
    ln -sf "$JAVA_HOME/bin/java" /usr/bin/java && \
    ln -sf "$JAVA_HOME/bin/javac" /usr/bin/javac && \
    ln -sf "$JAVA_HOME/bin/jar" /usr/bin/jar

# Also install Java 25 for BuildTools (latest MC versions may need it)
RUN wget -q https://download.oracle.com/java/25/latest/jdk-25_linux-x64_bin.tar.gz -O /tmp/jdk25.tar.gz && \
    tar -xzf /tmp/jdk25.tar.gz -C /usr/lib/jvm && \
    rm /tmp/jdk25.tar.gz || true

# ---- Application Setup ----
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Ensure data directories exist
RUN mkdir -p data/servers data/velocity

# ---- Supervisor Configuration ----
# Supervisor runs both the Python webserver and Velocity proxy
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# ---- Ports ----
# 25565 = Velocity proxy (the ONLY port exposed to players)
# 8000  = Web management interface (optional, for admin access)
EXPOSE 25565
EXPOSE 8000

# ---- Entrypoint ----
# Use supervisor to manage both processes
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
