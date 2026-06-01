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

    # Without a baseline server timestamp in latest.log there's nothing to
    # anchor commands to — bail rather than dumping unrelated history in.
    if first_log_ts is None:
        return

    added = 0
    for c in cmds:
        local = c["sent_at"].astimezone()
        if abs((local - anchor).total_seconds()) > 86400:
            continue
        ts = local.strftime("%H:%M:%S")
        if ts < first_log_ts:
            continue
        line = f"[{ts}] [Console/CMD]: {c['command']}\n"
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


def stop_server(server_name, send_cmd=True):
    """
    Stop a Minecraft server's Docker container gracefully by:
    1. Issuing "stop" command to container stdin (if send_cmd is True).
    2. Waiting up to 30 seconds for graceful shutdown.
    3. Appending the ThreadedAnvilChunkStorage message to latest.log.
    4. Forcefully stopping/killing the container if needed.
    """
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    container_name = info.get("container_name") or f"mc-{server_name}"

    try:
        client = docker.from_env()
        container = client.containers.get(container_name)

        if container.status == "running":
            print(f"[Docker] Gracefully stopping server '{server_name}'...")
            
            if send_cmd:
                try:
                    sock = container.attach_socket(params={'stdin': 1, 'stream': 1})
                    payload = ("stop\n").encode("utf-8")
                    if hasattr(sock, '_sock'):
                        sock._sock.sendall(payload)
                    elif hasattr(sock, 'send'):
                        sock.send(payload)
                    else:
                        sock.write(payload)
                    sock.close()
                    print(f"[Docker] Sent 'stop' command to stdin of '{container_name}'.")
                except Exception as stdin_err:
                    print(f"[Docker] Failed to send stop command to stdin: {stdin_err}")
            
            # Poll status for up to 30 seconds
            import time
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    container.reload()
                    if container.status != "running":
                        break
                except Exception:
                    break
                time.sleep(0.5)

            # Append the ThreadedAnvilChunkStorage log line to latest.log
            import datetime
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            now = datetime.datetime.now()
            day = now.strftime("%d")
            month = months[now.month - 1]
            year = now.strftime("%Y")
            time_str = now.strftime("%H:%M:%S.%f")[:-3]
            timestamp = f"{day}{month}{year} {time_str}"
            
            log_line = f"[{timestamp}] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: ThreadedAnvilChunkStorage: All dimensions are saved\n"
            
            log_path = f"data/servers/{server_name}/logs/latest.log"
            if os.path.exists(log_path):
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(log_line)
                    print(f"[Docker] Wrote saved-chunks sentinel log to {log_path}")
                except Exception as write_err:
                    print(f"[Docker] Failed to write saved chunks line to latest.log: {write_err}")

            # Stop/kill container explicitly to mark it as stopped for Docker restart policy
            try:
                container.reload()
                if container.status == "running":
                    container.stop(timeout=10)
            except Exception as stop_err:
                print(f"[Docker] container.stop exception: {stop_err}")

            print(f"[Docker] Container '{container_name}' stopped.")
            return f"Server '{server_name}' stopped successfully."
        else:
            return f"Server '{server_name}' is not running (status: {container.status})."

    except docker.errors.NotFound:
        return f"Container '{container_name}' not found. Server may not be running."
    except Exception as e:
        return f"Error stopping server '{server_name}': {str(e)}"
