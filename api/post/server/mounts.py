"""
Shared helper for building Docker volume mounts with a subpath.

Minecraft server data lives in the ``mc-data`` Docker named volume at
``servers/<name>/``. Child containers (download, build, run) mount that
subpath at ``/data`` so each server only sees its own files and the UID
boundary is enforced by Docker rather than by directory permissions.
"""

from docker.types import Mount
import os

_OWN_CONTAINER = None


def get_own_container():
    """
    Return the Docker container object for the container we are running in,
    or None when not running inside Docker / the socket is unavailable.

    The lookup uses the container hostname, which Docker sets to the short
    container id by default. The result is cached for the process lifetime.
    """
    global _OWN_CONTAINER
    if _OWN_CONTAINER is not None:
        return _OWN_CONTAINER
    import socket
    import docker
    try:
        client = docker.from_env()
        _OWN_CONTAINER = client.containers.get(socket.gethostname())
    except Exception:
        _OWN_CONTAINER = None
    return _OWN_CONTAINER


def get_compose_project(default="minecraftservertool"):
    """
    Return the Docker Compose project name our own container belongs to.

    Coolify (and plain ``docker compose -p``) pick arbitrary project names,
    so sibling containers must be located through this label rather than
    through fixed container names.
    """
    me = get_own_container()
    if me is not None:
        project = me.labels.get("com.docker.compose.project")
        if project:
            return project
    return default


def find_sibling_container(service_name, client=None):
    """
    Find the container of compose service ``service_name`` in our own
    compose project (e.g. ``infrared``). Returns None when not found.
    """
    import docker
    me = get_own_container()
    if me is None:
        return None
    project = me.labels.get("com.docker.compose.project")
    if not project:
        return None
    client = client or docker.from_env()
    try:
        matches = client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={project}",
                    f"com.docker.compose.service={service_name}",
                ]
            },
        )
    except Exception:
        return None
    # Ignore one-off containers (docker compose run) if any slipped through.
    matches = [c for c in matches if c.labels.get("com.docker.compose.oneoff", "False") != "True"]
    return matches[0] if matches else None


def get_server_data_volume():
    """
    Find the actual volume name mounted to /app/data in this container.
    Falls back to 'mc-data' if not running in Docker or unable to inspect.

    This keeps working when the orchestrator renames the volume (Coolify
    prefixes named volumes with the resource uuid; ``docker compose -p``
    prefixes them with the project name).
    """
    me = get_own_container()
    if me is not None:
        for mount in me.attrs.get("Mounts", []):
            if mount.get("Destination") == "/app/data":
                if mount.get("Type") == "volume" and mount.get("Name"):
                    return mount.get("Name")
    return "mc-data"

SERVER_DATA_VOLUME = get_server_data_volume()


def volume_subpath_mount(target, volume_name, subpath, read_only=False):
    """Return a Mount that binds ``volume_name[/subpath]`` at ``target``."""
    import docker
    client = docker.from_env()
    vol = client.volumes.get(volume_name)
    host_path = os.path.join(vol.attrs["Mountpoint"], subpath)
    os.makedirs(host_path, exist_ok=True)
    return Mount(
        target=target,
        source=host_path,
        type="bind",
        read_only=read_only,
    )


def server_data_mount(server_name, target="/data", read_only=False):
    """Mount the per-server subpath of the shared mc-data volume."""
    return volume_subpath_mount(
        target=target,
        volume_name=SERVER_DATA_VOLUME,
        subpath=f"servers/{server_name}",
        read_only=read_only,
    )


def ensure_volume_directory(volume_name, subpath):
    """
    Ensure that a subdirectory exists inside a Docker volume.
    Spawns a quick ephemeral container that mounts the root of the volume and runs mkdir -p.
    """
    import docker
    client = docker.from_env()
    try:
        # eclipse-temurin:25-jdk is already pulled/built on the host for servers
        client.containers.run(
            image="eclipse-temurin:25-jdk",
            command=f"mkdir -p /vol/{subpath}",
            mounts=[
                docker.types.Mount(
                    target="/vol",
                    source=volume_name,
                    type="volume"
                )
            ],
            remove=True
        )
        print(f"[Docker] Ensured volume directory '{volume_name}:{subpath}' exists.")
    except Exception as e:
        print(f"[Docker] Warning: failed to ensure volume directory '{volume_name}:{subpath}': {e}")


def write_volume_file(volume_name, subpath, content):
    """
    Write a file inside a Docker volume.
    Also writes it locally to the 'data' directory for local environment visibility.
    """
    import os
    import base64
    import docker

    # 1. Write locally
    local_path = os.path.join("data", subpath)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        with open(local_path, "w") as f:
            f.write(content)
        print(f"[Local] Wrote file '{local_path}'.")
    except Exception as e:
        print(f"[Local] Warning: could not write local file '{local_path}': {e}")

    # 2. Write in named volume
    client = docker.from_env()
    try:
        b64_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        cmd = f"bash -c 'mkdir -p /vol/{os.path.dirname(subpath)} && echo {b64_content} | base64 -d > /vol/{subpath}'"
        client.containers.run(
            image="eclipse-temurin:25-jdk",
            command=cmd,
            mounts=[
                docker.types.Mount(
                    target="/vol",
                    source=volume_name,
                    type="volume"
                )
            ],
            remove=True
        )
        print(f"[Docker] Wrote file '{volume_name}:{subpath}' inside volume.")
    except Exception as e:
        print(f"[Docker] Warning: failed to write volume file '{volume_name}:{subpath}': {e}")


def get_compose_labels(service_name):
    """
    Generate Docker Compose labels so dynamically spawned sibling containers
    are grouped into the same container/compose stack.

    Only ``com.docker.compose.*`` labels are copied on purpose: Coolify
    identifies the containers it owns by its own ``coolify.*`` labels, so the
    spawned Minecraft containers are left alone when the stack is redeployed.
    """
    return {
        "com.docker.compose.project": get_compose_project(),
        "com.docker.compose.service": service_name,
        "com.docker.compose.oneoff": "False",
    }
