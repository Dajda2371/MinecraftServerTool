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
#
# Real player IPs: Infrared forwards the player's address in a PROXY
# protocol header to MMPROXY_PORT. go-mmproxy strips the header and opens
# the connection to Java on 127.0.0.1:<server-port> with the player's IP
# as the TCP source address (IP_TRANSPARENT + loopback policy routing), so
# the server logs/bans the real address. Requires CAP_NET_ADMIN; without
# it we log a warning and run without the helper (Infrared then routes
# directly to the server port, as before).
set -e

chown -R 1000:1000 /data

# --- Java runtime selection -------------------------------------------------
# JAVA_VERSION (set by the management container per server) picks one of the
# runtimes bundled in the image (/opt/java/jdk8, jdk16, jdk17, jdk21, jdk25)
# or "custom" for a runtime mounted at /opt/java/custom. Unknown or
# unset values keep the image default. Spigot 1.21.x, for example, refuses to
# start on Java 25 ("Only up to Java 23 is supported").
if [ "${JAVA_VERSION:-}" = "custom" ]; then
    # A user-provided JDK/JRE mounted read-only by the management container.
    if [ -x "/opt/java/custom/bin/java" ]; then
        export JAVA_HOME="/opt/java/custom"
        export PATH="${JAVA_HOME}/bin:${PATH}"
    else
        echo "[entrypoint] WARNING: custom runtime not mounted at /opt/java/custom; using the default runtime."
    fi
elif [ -n "${JAVA_VERSION:-}" ]; then
    if [ -x "/opt/java/jdk${JAVA_VERSION}/bin/java" ]; then
        export JAVA_HOME="/opt/java/jdk${JAVA_VERSION}"
        export PATH="${JAVA_HOME}/bin:${PATH}"
    else
        echo "[entrypoint] WARNING: Java ${JAVA_VERSION} is not bundled in this image; using the default runtime."
    fi
fi
echo "[entrypoint] Java runtime: $(java -version 2>&1 | grep -m1 -i 'version') (JAVA_HOME=${JAVA_HOME:-/opt/java/openjdk})"

MMPROXY_PORT="${MMPROXY_PORT:-25566}"
MC_PORT="$(grep -E '^server-port=' /data/server.properties 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]')"
MC_PORT="${MC_PORT:-25565}"

if [ "${REAL_IP_PROXY:-1}" != "0" ] && command -v go-mmproxy >/dev/null 2>&1; then
    if ip rule add from 127.0.0.1/8 iif lo table 123 2>/dev/null \
       && ip route add local 0.0.0.0/0 dev lo table 123 2>/dev/null; then
        # IPv6 loopback rules are best-effort (IPv6 may be disabled in the netns).
        ip -6 rule add from ::1/128 iif lo table 123 2>/dev/null || true
        ip -6 route add local ::/0 dev lo table 123 2>/dev/null || true
        go-mmproxy -l "0.0.0.0:${MMPROXY_PORT}" -4 "127.0.0.1:${MC_PORT}" -6 "[::1]:${MC_PORT}" -p tcp &
        echo "[entrypoint] go-mmproxy: :${MMPROXY_PORT} (PROXY protocol) -> 127.0.0.1:${MC_PORT}; players keep their real IP."
    else
        echo "[entrypoint] WARNING: cannot install loopback routing rules (CAP_NET_ADMIN missing?)." \
             "Running without go-mmproxy; players will appear with the proxy's address."
    fi
fi

exec gosu 1000:1000 "$@"
