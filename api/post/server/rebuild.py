import os
import re
import socket
import threading
import time
from mcrcon import MCRcon
from api.post.server.create import run_build_tools, download_vanilla_jar
from api.db import get_server_info, update_server_info
from api.get.server.console import get_server_version
from api.get.server.console import get_server_properties
from api.get.server.console import is_server_running

def rebuild_server(server_name):
    print(f"Rebuilding server '{server_name}'...")

    # 1. Detect info
    info = get_server_info(server_name)
    server_type = info.get("type", "spigot") if info else "spigot"
    version = get_server_version(server_name)
    print(f"Detected version: {version}, type: {server_type}")

    # 2. Stop server if running
    properties = get_server_properties(server_name)
    if properties and "rcon.port" in properties and "rcon.password" in properties:
        rcon_port = int(properties["rcon.port"])
        rcon_password = properties["rcon.password"]
        try:
            with MCRcon("localhost", rcon_password, rcon_port) as rcon:
                if is_server_running(rcon):
                    print("Server is running. Stopping it...")
                    rcon.command("stop")
                    time.sleep(5)
        except Exception:
            pass

    # 3. Rebuild based on server type
    if server_type == "vanilla":
        try:
            jar_name = download_vanilla_jar(server_name, version)
            full_jar_path = f"data/servers/{server_name}/{jar_name}"
            owner = info.get("owner", "admin") if info else "admin"
            update_server_info(server_name, owner, server_type, version, full_jar_path)
            print("Server info updated in database.")
            return "Server rebuild complete and info saved."
        except Exception as e:
            print(f"Failed to download vanilla JAR: {e}")
            return "Server rebuild failed."
    else:
        success, msg = run_build_tools(server_name, version)
        print(msg)

        if success:
            jar_path = ""
            try:
                with open(f"data/servers/{server_name}/start.sh", "r") as f:
                    content = f.read()
                    match = re.search(r"-jar\s+(.*?\.jar)", content)
                    if match:
                        jar_path = match.group(1)
            except Exception:
                pass

            full_jar_path = f"data/servers/{server_name}/{jar_path}"
            owner = info.get("owner", "admin") if info else "admin"
            update_server_info(server_name, owner, server_type, version, full_jar_path)
            print("Server info updated in database.")

            return "Server rebuild complete and info saved."
        else:
            return "Server rebuild failed."
