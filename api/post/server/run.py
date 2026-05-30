"""
Launch a Minecraft server as an isolated Docker child container on the mc-net network.

Key properties:
- No published ports — only reachable via Infrared on the internal Docker network.
- Named volume for world data persistence.
- Non-root user running the server process.
- Connects to mc-net so Infrared can route to it by container name.
"""

import os
import docker

from api.db import get_server_info, update_server_info
from api.infrared import reload_proxy_config
from api.post.server.mounts import server_data_mount, write_volume_file, SERVER_DATA_VOLUME, get_compose_labels

# Docker network name shared by all server containers and the management container
DOCKER_NETWORK = "mc-net"

# Default server image — built from Dockerfile.server via the
# mc-server-base compose service. Ships with gosu + our entrypoint that
# chowns /data and drops to UID 1000 before exec'ing Java.
DEFAULT_SERVER_IMAGE = "mc-server-base:latest"


def ensure_network(client):
    """Ensure the mc-net Docker network exists."""
    try:
        client.networks.get(DOCKER_NETWORK)
    except docker.errors.NotFound:
        print(f"[Docker] Creating network '{DOCKER_NETWORK}'...")
        client.networks.create(DOCKER_NETWORK, driver="bridge")


def configure_server_properties(server_path, port):
    """
    Ensure server.properties has correct settings for running behind Infrared:
    - online-mode=true (backend handles Mojang auth; Infrared only routes)
    - server-port set to the assigned internal port
    """
    props_path = os.path.join(server_path, "server.properties")
    properties = {}

    # Read existing properties if the file exists
    if os.path.exists(props_path):
        with open(props_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    properties[key.strip()] = value.strip()

    # Set required values: Infrared is a connection-level proxy, so each backend
    # runs online-mode=true and does its own Mojang authentication.
    properties["online-mode"] = "true"
    properties["server-port"] = str(port)

    # Ensure RCON is enabled for console access
    if "enable-rcon" not in properties:
        properties["enable-rcon"] = "true"
    if "rcon.password" not in properties:
        properties["rcon.password"] = "admin"
    if "rcon.port" not in properties:
        properties["rcon.port"] = "25575"

    # Write back
    with open(props_path, "w") as f:
        for key, value in properties.items():
            f.write(f"{key}={value}\n")


def run_server(server_name):
    """
    Start a Minecraft server inside an isolated Docker container on mc-net.

    The container:
    - Uses the server's assigned internal port (not published to host)
    - Connects to mc-net for Infrared routing
    - Mounts the server data as a bind volume
    - Runs as non-root user
    """
    # Get server details from DB
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    # Verify EULA has been agreed to before starting
    if not is_eula_agreed(server_name):
        return f"Error: You must agree to the EULA before starting server '{server_name}'."

    client = docker.from_env()
    ensure_network(client)

    # Server data lives in the mc-data named volume at servers/<name>/.
    # mc-tool accesses it through its own /app/data mount; child
    # containers mount the subpath directly.
    server_local_path = os.path.abspath(f"data/servers/{server_name}")

    container_name = info.get("container_name") or f"mc-{server_name}"
    port = info.get("port") or 25565
    memory_mb = info.get("memory_mb") or 1024

    # Configure server.properties (online-mode=true, correct port)
    configure_server_properties(server_local_path, port)

    # Sync server.properties to Docker volume
    try:
        with open(os.path.join(server_local_path, "server.properties"), "r") as f:
            props_content = f.read()
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/server.properties", props_content)
    except Exception as e:
        print(f"[Docker] Warning: failed to sync server.properties to volume: {e}")

    # No automatic EULA write here anymore because EULA must be explicitly agreed via the UI.

    # Remove existing container if any
    try:
        old_container = client.containers.get(container_name)
        print(f"[Docker] Stopping existing container '{container_name}'...")
        old_container.stop(timeout=30)
        old_container.remove()
    except docker.errors.NotFound:
        pass

    # Determine the JAR filename
    jar_filename = os.path.basename(info["jar_path"]) if info.get("jar_path") else "server.jar"

    # Command to run inside the container
    # Set Java heap slightly smaller than container limit to avoid OOM kills by Docker
    java_heap = int(memory_mb * 0.8)
    if java_heap < 512:
        java_heap = 512
        
    cmd = f"java -Xmx{java_heap}M -Xms{java_heap}M -jar {jar_filename} nogui --port {port}"

    try:
        print(f"[Docker] Starting container '{container_name}' on internal port {port}...")
        container = client.containers.run(
            image=DEFAULT_SERVER_IMAGE,
            command=cmd,
            name=container_name,
            detach=True,
            stdin_open=True,
            # NO port publishing — only reachable within mc-net
            network=DOCKER_NETWORK,
            mounts=[server_data_mount(server_name)],
            working_dir="/data",
            # Entrypoint in the image starts as root, chowns /data, then
            # drops to UID 1000 via gosu before exec'ing Java.
            environment={
                "JAVA_TOOL_OPTIONS": "-XX:+UseContainerSupport",
            },
            # Resource limits
            mem_limit=f"{memory_mb}m",
            # Restart policy
            restart_policy={"Name": "unless-stopped"},
            labels=get_compose_labels(f"server-{server_name}"),
        )

        # Update DB with container info
        update_server_info(
            server_name,
            info["owner"],
            info["type"],
            info["version"],
            info["jar_path"],
            port=port,
            container_name=container_name,
        )

        # Reload Infrared config so it knows about this server
        try:
            reload_proxy_config()
        except Exception as e:
            print(f"[Infrared] Warning: Could not reload Infrared config: {e}")

        return (
            f"Server '{server_name}' started in container '{container_name}' "
            f"on internal port {port} (mc-net). "
            f"Not published to host — accessible only via Infrared proxy."
        )

    except Exception as e:
        return f"Failed to start container for '{server_name}': {str(e)}"


def get_server_status(server_name):
    """Check the status of a server's Docker container."""
    info = get_server_info(server_name)
    if not info:
        return f"Server '{server_name}' not found in database."

    container_name = info.get("container_name") or f"mc-{server_name}"
    
    if info.get("jar_path") in ("BUILDING...", "DOWNLOADING..."):
        return {
            "name": server_name,
            "container": container_name,
            "status": "CREATING",
            "port": info.get("port"),
            "hostname": info.get("hostname"),
        }

    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        return {
            "name": server_name,
            "container": container_name,
            "status": container.status,
            "port": info.get("port"),
            "hostname": info.get("hostname"),
        }
    except docker.errors.NotFound:
        return {
            "name": server_name,
            "container": container_name,
            "status": "not running",
            "port": info.get("port"),
            "hostname": info.get("hostname"),
        }
    except Exception as e:
        print(f"[Docker] Error getting status for '{server_name}': {e}")
        return {
            "name": server_name,
            "container": container_name,
            "status": "UNKNOWN",
            "port": info.get("port"),
            "hostname": info.get("hostname"),
        }


def is_eula_agreed(server_name):
    """Check if the server's eula.txt exists and has eula=true."""
    import os
    local_path = os.path.join("data", "servers", server_name, "eula.txt")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r") as f:
                content = f.read()
            return "eula=true" in content.lower().replace(" ", "")
        except Exception:
            pass
    return False


def agree_to_eula(server_name):
    """
    Update eula.txt for a server to set eula=true,
    preserving comments and date lines exactly.
    """
    import os
    
    local_path = os.path.join("data", "servers", server_name, "eula.txt")
    if not os.path.exists(local_path):
        import time
        date_str = time.strftime("#%a %b %d %H:%M:%S UTC %Y")
        content = (
            "#By changing the setting below to TRUE you are agreeing to the Minecraft EULA (https://aka.ms/MinecraftEULA).\n"
            f"{date_str}\n"
            "eula=true\n"
        )
    else:
        with open(local_path, "r") as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if line.strip().lower().replace(" ", "") == "eula=false":
                # Find leading indentation or keep spacing, change eula=false to eula=true
                leading = line[:line.lower().find("eula")]
                new_lines.append(f"{leading}eula=true\n")
            else:
                new_lines.append(line)
        content = "".join(new_lines)

    # Write to local file and named volume
    write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/eula.txt", content)
    return "EULA agreed successfully."