import os
import docker
from api.db import get_server_info

def run_server(server_name):
    # Get server details from DB
    info = get_server_info(server_name)
    if not info:
        return f"Error: Server '{server_name}' not found in database."

    client = docker.from_env()
    
    # Path handling for Docker-out-of-Docker
    # HOST_DATA_PATH should be the host-side path to the 'data' directory
    host_data_path = os.getenv("MC_HOST_DATA_DIR", os.path.abspath("data"))
    server_host_path = f"{host_data_path}/servers/{server_name}"
    
    container_name = f"mc-{server_name}"
    
    # Remove existing container if any
    try:
        old_container = client.containers.get(container_name)
        old_container.stop()
        old_container.remove()
    except docker.errors.NotFound:
        pass

    # Command to run inside the container
    # We use the jar_path from DB, but we only need the filename since we mount the directory to /server
    jar_filename = os.path.basename(info["jar_path"])
    cmd = f"java -Xmx1024M -Xms1024M -jar {jar_filename} nogui"

    try:
        container = client.containers.run(
            image="openjdk:25-jdk-slim",
            command=cmd,
            name=container_name,
            detach=True,
            ports={f"25565/tcp": info["port"]},
            volumes={
                server_host_path: {
                    'bind': '/server',
                    'mode': 'rw'
                }
            },
            working_dir='/server'
        )
        return f"Server '{server_name}' started in container '{container_name}' on port {info['port']}."
    except Exception as e:
        return f"Failed to start container for '{server_name}': {str(e)}"