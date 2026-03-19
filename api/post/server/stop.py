"""
Stop a running Minecraft server container.
"""

import docker
from api.db import get_server_info


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
            return f"Server '{server_name}' stopped successfully."
        else:
            return f"Server '{server_name}' is not running (status: {container.status})."

    except docker.errors.NotFound:
        return f"Container '{container_name}' not found. Server may not be running."
    except Exception as e:
        return f"Error stopping server '{server_name}': {str(e)}"
