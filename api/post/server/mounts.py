"""
Shared helper for building Docker volume mounts with a subpath.

Minecraft server data lives in the ``mc-data`` Docker named volume at
``servers/<name>/``. Child containers (download, build, run) mount that
subpath at ``/data`` so each server only sees its own files and the UID
boundary is enforced by Docker rather than by directory permissions.

docker-py 7.1.0 does not yet expose ``subpath`` as a keyword argument to
``Mount`` (it landed on ``main`` after release). The engine API supports
the field via ``VolumeOptions.Subpath`` since Docker 25.0 / API 1.45,
so we set it on the returned ``Mount`` dict directly — ``Mount``
subclasses ``dict`` and is serialised verbatim into the HostConfig.
"""

from docker.types import Mount

SERVER_DATA_VOLUME = "mc-data"


def volume_subpath_mount(target, volume_name, subpath, read_only=False):
    """Return a Mount that binds ``volume_name[/subpath]`` at ``target``."""
    mount = Mount(
        target=target,
        source=volume_name,
        type="volume",
        read_only=read_only,
    )
    if subpath:
        # Merge with any VolumeOptions Mount already set (currently none).
        opts = mount.get("VolumeOptions", {})
        opts["Subpath"] = subpath
        mount["VolumeOptions"] = opts
    return mount


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
        # eclipse-temurin:21-jdk is already pulled/built on the host for servers
        client.containers.run(
            image="eclipse-temurin:21-jdk",
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

