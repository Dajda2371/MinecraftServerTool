"""
Delete a Minecraft server — stop its container, remove it, and optionally remove data.
"""

import os
import shutil
import docker

from api.db import get_server_info, delete_server as db_delete_server
from api.velocity import reload_velocity_config


def delete_server(server_name, remove_data=False):
    """
    Delete a Minecraft server:
    1. Stop and remove the Docker container
    2. Remove the server from the database
    3. Optionally remove server data files
    4. Reload Velocity config
    """
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    container_name = info.get("container_name") or f"mc-{server_name}"

    # Stop and remove Docker container
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        if container.status == "running":
            print(f"[Docker] Stopping container '{container_name}'...")
            container.stop(timeout=30)
        print(f"[Docker] Removing container '{container_name}'...")
        container.remove()
    except docker.errors.NotFound:
        print(f"[Docker] Container '{container_name}' not found (already removed).")
    except Exception as e:
        print(f"[Docker] Warning: Could not remove container: {e}")

    # Remove from database
    db_delete_server(server_name)
    print(f"[DB] Server '{server_name}' removed from database.")

    # Optionally remove data
    if remove_data:
        server_data_path = os.path.abspath(f"data/servers/{server_name}")
        if os.path.exists(server_data_path):
            print(f"[Data] Removing server data at '{server_data_path}'...")
            shutil.rmtree(server_data_path)
            print(f"[Data] Server data removed.")
        else:
            print(f"[Data] No data directory found at '{server_data_path}'.")

    # Reload Velocity config to remove the server entry
    try:
        reload_velocity_config()
    except Exception as e:
        print(f"[Velocity] Warning: Could not reload Velocity config: {e}")

    return f"Server '{server_name}' has been deleted."
