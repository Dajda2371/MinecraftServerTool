"""
Launch a Minecraft server as an isolated Docker child container on the mc-net network.

Key properties:
- No published ports — only reachable via Velocity on the internal Docker network.
- Named volume for world data persistence.
- Non-root user running the server process.
- Connects to mc-net so Velocity can route to it by container name.
"""

import os
import docker

from api.db import get_server_info, update_server_info
from api.velocity import reload_velocity_config

# Docker network name shared by all server containers and the management container
DOCKER_NETWORK = "mc-net"

# Default server image
DEFAULT_SERVER_IMAGE = "openjdk:21-jre-slim"


def ensure_network(client):
    """Ensure the mc-net Docker network exists."""
    try:
        client.networks.get(DOCKER_NETWORK)
    except docker.errors.NotFound:
        print(f"[Docker] Creating network '{DOCKER_NETWORK}'...")
        client.networks.create(DOCKER_NETWORK, driver="bridge")


def configure_server_properties(server_path, port):
    """
    Ensure server.properties has correct settings for running behind Velocity:
    - online-mode=false (Velocity handles authentication)
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

    # Set required values for Velocity
    properties["online-mode"] = "false"
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


def configure_velocity_forwarding(server_path, forwarding_secret, server_type="spigot"):
    """
    Configure Velocity modern forwarding on the server.
    
    For Paper/Spigot servers, this writes to:
    - config/paper-global.yml (Paper 1.19+)
    - spigot.yml as fallback
    """
    # Paper global config for Velocity forwarding
    paper_config_dir = os.path.join(server_path, "config")
    os.makedirs(paper_config_dir, exist_ok=True)
    
    paper_global_path = os.path.join(paper_config_dir, "paper-global.yml")
    
    paper_config = f"""# Paper Global Configuration — auto-generated for Velocity forwarding
proxies:
  velocity:
    enabled: true
    online-mode: true
    secret: "{forwarding_secret}"
"""
    
    with open(paper_global_path, "w") as f:
        f.write(paper_config)


def run_server(server_name):
    """
    Start a Minecraft server inside an isolated Docker container on mc-net.
    
    The container:
    - Uses the server's assigned internal port (not published to host)
    - Connects to mc-net for Velocity routing
    - Mounts the server data as a bind volume
    - Runs as non-root user
    """
    # Get server details from DB
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    client = docker.from_env()
    ensure_network(client)

    # Path handling for Docker-out-of-Docker
    host_data_path = os.getenv("MC_HOST_DATA_DIR", os.path.abspath("data"))
    server_host_path = f"{host_data_path}/servers/{server_name}"
    server_local_path = os.path.abspath(f"data/servers/{server_name}")

    container_name = info.get("container_name") or f"mc-{server_name}"
    port = info.get("port") or 25566
    forwarding_secret = info.get("forwarding_secret") or ""

    # Configure server.properties for Velocity
    configure_server_properties(server_local_path, port)

    # Configure Velocity modern forwarding
    if forwarding_secret:
        configure_velocity_forwarding(server_local_path, forwarding_secret, info.get("type", "spigot"))

    # Ensure eula.txt exists
    eula_path = os.path.join(server_local_path, "eula.txt")
    if not os.path.exists(eula_path):
        with open(eula_path, "w") as f:
            f.write("eula=true\n")

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
    cmd = f"java -Xmx1024M -Xms1024M -jar {jar_filename} nogui --port {port}"

    try:
        print(f"[Docker] Starting container '{container_name}' on internal port {port}...")
        container = client.containers.run(
            image=DEFAULT_SERVER_IMAGE,
            command=cmd,
            name=container_name,
            detach=True,
            # NO port publishing — only reachable within mc-net
            network=DOCKER_NETWORK,
            volumes={
                server_host_path: {
                    "bind": "/data",
                    "mode": "rw",
                }
            },
            working_dir="/data",
            # Run as non-root user (UID 1000)
            user="1000:1000",
            # Environment variables
            environment={
                "JAVA_TOOL_OPTIONS": "-XX:+UseContainerSupport",
            },
            # Resource limits
            mem_limit="2g",
            # Restart policy
            restart_policy={"Name": "unless-stopped"},
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

        # Reload Velocity config so it knows about this server
        try:
            reload_velocity_config()
        except Exception as e:
            print(f"[Velocity] Warning: Could not reload Velocity config: {e}")

        return (
            f"Server '{server_name}' started in container '{container_name}' "
            f"on internal port {port} (mc-net). "
            f"Not published to host — accessible only via Velocity proxy."
        )

    except Exception as e:
        return f"Failed to start container for '{server_name}': {str(e)}"


def get_server_status(server_name):
    """Check the status of a server's Docker container."""
    info = get_server_info(server_name)
    if not info:
        return f"Server '{server_name}' not found in database."

    container_name = info.get("container_name") or f"mc-{server_name}"

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