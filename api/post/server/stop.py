"""
Stop a running Minecraft server container.
"""

import os
import re
from datetime import datetime

import docker

import api.db
from api.db import get_server_info


def inject_commands_into_log(server_name):
    """
    Merge console commands stored in PostgreSQL into the server's latest.log
    so they survive Minecraft's log rotation on next startup. Idempotent:
    skips commands whose formatted line is already present.
    """
    log_path = f"data/servers/{server_name}/logs/latest.log"
    if not os.path.exists(log_path):
        return

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_lines = f.readlines()
    except Exception as e:
        print(f"[Inject] Could not read latest.log for '{server_name}': {e}")
        return

    try:
        cmds = api.db.get_console_commands(server_name, limit=10000)
    except Exception as e:
        print(f"[Inject] Could not fetch DB commands for '{server_name}': {e}")
        return

    if not cmds:
        return

    # latest.log only carries HH:MM:SS — anchor to the file's mtime so we
    # don't pull in commands from an unrelated previous session.
    try:
        anchor = datetime.fromtimestamp(os.path.getmtime(log_path)).astimezone()
    except Exception:
        anchor = datetime.now().astimezone()

    ts_re = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
    existing_lines = set(log_lines)

    entries = []
    first_log_ts = None
    for raw in log_lines:
        m = ts_re.match(raw)
        if m:
            ts_val = m.group(1)
            if first_log_ts is None:
                first_log_ts = ts_val
            entries.append((ts_val, 1, raw))
        else:
            entries.append(("00:00:00", 1, raw))

    added = 0
    for c in cmds:
        local = c["sent_at"].astimezone()
        if abs((local - anchor).total_seconds()) > 86400:
            continue
        ts = local.strftime("%H:%M:%S")
        if first_log_ts is not None and ts < first_log_ts:
            continue
        line = f"[{ts}] [Console/CMD]: > {c['command']}\n"
        if line in existing_lines:
            continue
        entries.append((ts, 0, line))
        added += 1

    if added == 0:
        return

    entries.sort(key=lambda x: (x[0], x[1]))

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("".join(line for _, _, line in entries))
        print(f"[Inject] Merged {added} command(s) into {log_path}")
    except Exception as e:
        print(f"[Inject] Could not write latest.log for '{server_name}': {e}")


def stop_server(server_name):
    """
    Stop a Minecraft server's Docker container gracefully.

    Sends SIGTERM and waits up to 30 seconds for graceful shutdown,
    then forcefully kills if needed.
    """
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    container_name = info.get("container_name") or f"mc-{server_name}"

    try:
        client = docker.from_env()
        container = client.containers.get(container_name)

        if container.status == "running":
            print(f"[Docker] Stopping container '{container_name}'...")
            container.stop(timeout=30)
            print(f"[Docker] Container '{container_name}' stopped.")
            inject_commands_into_log(server_name)
            return f"Server '{server_name}' stopped successfully."
        else:
            return f"Server '{server_name}' is not running (status: {container.status})."

    except docker.errors.NotFound:
        return f"Container '{container_name}' not found. Server may not be running."
    except Exception as e:
        return f"Error stopping server '{server_name}': {str(e)}"
