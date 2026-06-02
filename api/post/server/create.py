import os
import re
import time
import threading

import docker
import requests

import api.get.lastbuildtoolsversion
from api.db import update_server_info, get_server_info
from api.get.forge import get_forge_versions
from api.post.server.mounts import (
    SERVER_DATA_VOLUME,
    server_data_mount,
    volume_subpath_mount,
    ensure_volume_directory,
    write_volume_file,
    get_compose_labels,
)

LASTBUILDTOOLSVERSION = api.get.lastbuildtoolsversion.last_buildtools_version()
BUILDTOOLSJAR = "BuildTools" + LASTBUILDTOOLSVERSION + ".jar"
DEFAULT_BUILD_JAVA = "25"

VANILLA_GIST_URL = "https://gist.githubusercontent.com/cliffano/77a982a7503669c3e1acb0a0cf6127e9/raw/minecraft-server-jar-downloads.md"

# Real-time Socket.IO log callback hook
log_callback = None

def register_log_callback(cb):
    global log_callback
    log_callback = cb


def fetch_vanilla_jar_url(version):
    """Fetch the vanilla server JAR download URL for a given Minecraft version from the gist."""
    print(f"Fetching vanilla JAR URL for version {version}...")
    response = requests.get(VANILLA_GIST_URL)
    response.raise_for_status()

    for line in response.text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "Server Jar" in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        # cols: ['', version, server_url, client_url, '']
        if len(cols) >= 4 and cols[1] == version:
            return cols[2]

    raise ValueError(f"Version '{version}' not found in vanilla JAR manifest.")


def run_vanilla_download_container(server_name, version, jar_url, jar_filename=None, memory_mb=512):
    """
    Download the vanilla server JAR inside an ephemeral Docker container with
    the server's data folder bind-mounted at /data. Mirrors the pattern used
    by run_build_tools_container so all "create/build" work happens in a
    sidecar container, never in the management container.

    Returns (success, message, jar_filename).
    """
    container_name = f"mc-download-{server_name}"
    image = f"eclipse-temurin:{DEFAULT_BUILD_JAVA}-jdk"
    if jar_filename is None:
        jar_filename = f"vanilla-{version}.jar"

    # Ensure volume directory exists before mounting subpath
    ensure_volume_directory(SERVER_DATA_VOLUME, f"servers/{server_name}")

    client = docker.from_env()

    # Remove stale download container if exists
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    print(f"Starting download container ({image}) for vanilla server '{server_name}' version {version}...")

    # Route entire command logs through tee to /data/creation.log so it can be read by UI
    command = (
        f'bash -c "'
        f"(apt-get update -qq && apt-get install -y -qq curl && "
        f"curl -fsSL -o /data/{jar_filename} '{jar_url}' && "
        f'chown -R 1000:1000 /data) 2>&1 | tee /data/creation.log"'
    )

    # Clear / prepare the host creation.log path early for tailing
    log_path = os.path.join("data", "servers", server_name, "creation.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write("")

    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        detach=True,
        mounts=[server_data_mount(server_name)],
        working_dir="/data",
        mem_limit=f"{memory_mb}m",
        labels=get_compose_labels(f"download-{server_name}"),
    )

    # Follow download log in real time via Socket.IO
    stop_event = threading.Event()
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event, server_name),
        daemon=True,
    )
    log_thread.start()

    result = container.wait()
    exit_code = result.get("StatusCode", -1)

    stop_event.set()
    log_thread.join()

    try:
        logs = container.logs().decode("utf-8", errors="replace")
    except Exception:
        logs = ""

    try:
        container.remove()
    except Exception:
        pass

    if exit_code != 0:
        return False, f"Vanilla JAR download failed (exit {exit_code}):\n{logs}", jar_filename

    return True, "Download successful.", jar_filename


def download_vanilla_jar(server_name, version, memory_mb=512):
    """Download the vanilla server JAR via an ephemeral container."""
    url = fetch_vanilla_jar_url(version)
    success, message, jar_name = run_vanilla_download_container(
        server_name, version, url, memory_mb=memory_mb
    )
    if not success:
        raise RuntimeError(message)
    print(f"Downloaded {jar_name} successfully.")
    return jar_name


def follow_log_file(path, stop_event, server_name=None):
    try:
        with open(path, "r") as f:
            f.seek(0, 2)  # move to end of file
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    print(line, end="")
                    if log_callback and server_name:
                        try:
                            log_callback(server_name, line)
                        except Exception as e:
                            print(f"[LogCallback Error] {e}")
                else:
                    time.sleep(0.25)
    except FileNotFoundError:
        pass


def download_build_tools(server_name):
    """Download BuildTools.jar into the server directory if not already present."""
    target_jar = f"data/servers/{server_name}/{BUILDTOOLSJAR}"
    unversioned_jar = f"data/servers/{server_name}/BuildTools.jar"

    if os.path.exists(target_jar):
        print(f"found existing {BUILDTOOLSJAR}, skipping download")
    elif os.path.exists(unversioned_jar):
        print(f"found existing BuildTools.jar, renaming to {BUILDTOOLSJAR}")
        os.rename(unversioned_jar, target_jar)
    else:
        url = "https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar"
        print(f"Downloading BuildTools from {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(target_jar, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Downloaded BuildTools.jar successfully.")


def run_build_tools_container(server_name, server_version, java_version=DEFAULT_BUILD_JAVA, memory_mb=1024):
    """
    Run BuildTools inside an ephemeral Docker container.
    Returns (success, message, log_content).
    """
    # Ensure volume subpaths exist before mounting them
    ensure_volume_directory(SERVER_DATA_VOLUME, f"servers/{server_name}")
    ensure_volume_directory(SERVER_DATA_VOLUME, ".buildtools-cache/m2")
    ensure_volume_directory(SERVER_DATA_VOLUME, ".buildtools-cache/repos")

    # BuildTools caches live as subpaths of the shared mc-data volume so we
    # don't introduce another top-level volume. mc-tool can seed them via
    # its own /app/data mount.
    os.makedirs("data/.buildtools-cache/m2", exist_ok=True)
    os.makedirs("data/.buildtools-cache/repos", exist_ok=True)
    log_path = os.path.join("data", "servers", server_name, "buildtools.log")
    container_name = f"mc-build-{server_name}"
    image = f"eclipse-temurin:{java_version}-jdk"

    # Clear log file
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write("")

    # Remove stale build container if exists
    client = docker.from_env()
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    print(f"Starting build container ({image}) for server '{server_name}' version {server_version}...")

    java_heap = int(memory_mb * 0.8)
    command = (
        f'bash -c "'
        f"apt-get update -qq && apt-get install -y -qq git && "
        f"for repo in Bukkit CraftBukkit Spigot BuildData; do "
        f"if [ ! -d /data/$repo ] && [ -d /cache/$repo ]; then "
        f"cp -a /cache/$repo /data/$repo; "
        f"fi; done && "
        f"java -Xmx{java_heap}m -jar {BUILDTOOLSJAR} --rev {server_version} --compile-if-changed 2>&1 | tee /data/buildtools.log && "
        f"for repo in Bukkit CraftBukkit Spigot BuildData; do "
        f"if [ -d /data/$repo ]; then "
        f"rm -rf /cache/$repo && cp -a /data/$repo /cache/$repo; "
        f"fi; done && "
        f'chown -R 1000:1000 /data"'
    )

    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        detach=True,
        mounts=[
            server_data_mount(server_name),
            volume_subpath_mount("/root/.m2", SERVER_DATA_VOLUME, ".buildtools-cache/m2"),
            volume_subpath_mount("/cache", SERVER_DATA_VOLUME, ".buildtools-cache/repos"),
        ],
        environment={
            "MAVEN_OPTS": f"-Xmx{java_heap}m",
        },
        working_dir="/data",
        mem_limit=f"{memory_mb}m",
        labels=get_compose_labels(f"build-{server_name}"),
    )

    # Follow build log in real time
    stop_event = threading.Event()
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event, server_name),
        daemon=True,
    )
    log_thread.start()

    # Wait for container to finish
    result = container.wait()
    exit_code = result.get("StatusCode", -1)

    stop_event.set()
    log_thread.join()

    # Read log content
    time.sleep(1)  # FS flush buffer
    log_content = ""
    try:
        with open(log_path, "r") as f:
            log_content = f.read()
    except FileNotFoundError:
        pass

    print(f"[Debug] Build container exited with code {exit_code}. Log length: {len(log_content)}")

    # Clean up container
    try:
        container.remove()
    except Exception:
        pass

    if "Success! Everything completed successfully." in log_content:
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        os.system(
            f"mv data/servers/{server_name}/spigot-{server_version}.jar "
            f"data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar"
        )
        return True, "Build successful.", log_content

    return False, "Build failed.", log_content


def run_build_tools(server_name, server_version, memory_mb=1024):
    """
    Run BuildTools in a Docker container with retry logic for network errors
    and Java version mismatches. Returns (success, message).
    """
    download_build_tools(server_name)

    max_retries = 5
    java_version = DEFAULT_BUILD_JAVA

    failure_patterns = [
        "connection timeout",
        "could not resolve host",
        "connection timed out",
        "connection reset",
        "timeout",
        "failed to connect",
        "error occurred: connection timeout error",
    ]

    for attempt in range(max_retries):
        success, message, log_content = run_build_tools_container(
            server_name, server_version, java_version, memory_mb=memory_mb
        )

        if success:
            return True, message

        # Check for Java version mismatch
        mismatch_match = re.search(
            r"requires Java versions between \[Java (\d+), Java (\d+)\]", log_content
        )
        if mismatch_match:
            required_max = mismatch_match.group(2)
            print(f"Java version mismatch. Retrying with Java {required_max}...")
            java_version = required_max
            continue

        # Check for network errors
        log_lower = log_content.lower()
        found_pattern = None
        for pattern in failure_patterns:
            if pattern in log_lower:
                found_pattern = pattern
                break

        if found_pattern:
            if attempt < max_retries - 1:
                print(f"[Debug] Match found for error pattern: '{found_pattern}'")
                print(f"\n[System] BuildTools encountered a network error. Retrying... (Attempt {attempt+2}/{max_retries})\n")
                time.sleep(10)
                continue
            else:
                print(f"[System] BuildTools failed after {max_retries} attempts due to network errors.")

        print(f"[Debug] Build failed. See buildtools.log for details.")
        break

    return False, "Failed to create server."


def create_server(server_name, server_type, server_version, owner="admin", hostname=None, memory_mb=1024):
    """
    Create a new Minecraft server.

    Args:
        server_name: Unique name for the server
        server_type: Server type (spigot, vanilla, paper)
        server_version: Minecraft version (e.g., "1.21.1")
        owner: Owner username
        hostname: Optional hostname for Infrared routing (e.g., "survival.mc.davidbenes.cz")
        memory_mb: Memory allocation in MB for the server
    """
    print("creating server...")
    os.makedirs(f"data/servers/{server_name}", exist_ok=True)

    # Generate hostname from config if not provided
    if hostname is None:
        try:
            from config import MC_SUBDOMAIN
            hostname = f"{server_name}.{MC_SUBDOMAIN}"
        except ImportError:
            hostname = f"{server_name}.mc.localhost"

    if server_type.lower() == "vanilla":
        update_server_info(
            server_name, owner, "vanilla", server_version, "DOWNLOADING...",
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        try:
            jar_name = download_vanilla_jar(server_name, server_version)
        except Exception as e:
            print(f"Failed to download vanilla JAR: {e}")
            import shutil
            shutil.rmtree(f"data/servers/{server_name}", ignore_errors=True)
            return "Failed to create server."

        import time
        date_str = time.strftime("#%a %b %d %H:%M:%S UTC %Y")
        eula_content = (
            "#By changing the setting below to TRUE you are agreeing to the Minecraft EULA (https://aka.ms/MinecraftEULA).\n"
            f"{date_str}\n"
            "eula=false\n"
        )
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/eula.txt", eula_content)

        server_props = (
            "server-port=25565\n"
            "enable-rcon=false\n"
            "rcon.password=admin\n"
            "rcon.port=25575\n"
            "online-mode=true\n"
        )
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/server.properties", server_props)

        full_jar_path = f"data/servers/{server_name}/{jar_name}"
        container_name = f"mc-{server_name}"

        update_server_info(
            server_name, owner, "vanilla", server_version, full_jar_path,
            hostname=hostname,
            container_name=container_name,
            memory_mb=memory_mb,
        )

        print(f"Vanilla server '{server_name}' created successfully with version {server_version}.")
        print(f"  Hostname: {hostname}")
        print(f"  Container: {container_name}")
        return f"Server '{server_name}' created successfully."

    elif server_type.lower() == "spigot":
        # Insert into DB early so it shows up as "Creating" in the UI
        update_server_info(
            server_name, owner, "spigot", server_version, "BUILDING...",
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        success, message = run_build_tools(server_name, server_version, memory_mb=memory_mb)
        if success:
            import time
            date_str = time.strftime("#%a %b %d %H:%M:%S UTC %Y")
            eula_content = (
                "#By changing the setting below to TRUE you are agreeing to the Minecraft EULA (https://aka.ms/MinecraftEULA).\n"
                f"{date_str}\n"
                "eula=false\n"
            )
            write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/eula.txt", eula_content)

            # Infrared proxies at the connection level — backend handles its own
            # Mojang auth (online-mode=true).
            server_props = (
                "server-port=25565\n"
                "enable-rcon=false\n"
                "rcon.password=admin\n"
                "rcon.port=25575\n"
                "online-mode=true\n"
            )
            write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/server.properties", server_props)

            full_jar_path = f"data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar"
            container_name = f"mc-{server_name}"

            update_server_info(
                server_name, owner, "spigot", server_version, full_jar_path,
                hostname=hostname,
                container_name=container_name,
                memory_mb=memory_mb,
            )

            print(f"Spigot server '{server_name}' created successfully with version {server_version}.")
            print(f"  Hostname: {hostname}")
            print(f"  Container: {container_name}")
            print(f"  Online-mode: true (backend handles auth, Infrared routes only)")
            return f"Server '{server_name}' created successfully."
        else:
            import shutil
            shutil.rmtree(f"data/servers/{server_name}", ignore_errors=True)
            return message

    elif server_type.lower() == "forge":
        # Parse mc_version and forge_version from version e.g. "1.20.1-47.4.20"
        parts = server_version.split("-")
        if len(parts) == 2:
            mc_version, forge_version = parts[0], parts[1]
        else:
            mc_version = server_version
            try:
                scraped = get_forge_versions(mc_version)
                if scraped.get("recommended"):
                    forge_version = scraped["recommended"]["version"]
                elif scraped.get("latest"):
                    forge_version = scraped["latest"]["version"]
                else:
                    raise ValueError("No forge version found.")
            except Exception:
                return f"Invalid version format '{server_version}' for Forge. Expected 'mc_version-forge_version' (e.g. 1.20.1-47.4.20)."

        # Try to find the installer URL
        try:
            scraped = get_forge_versions(mc_version)
            url = None
            for v in scraped["versions"]:
                if v["version"] == forge_version:
                    url = v["url"]
                    break
            if not url:
                if scraped.get("recommended") and scraped["recommended"]["version"] == forge_version:
                    url = scraped["recommended"]["url"]
                elif scraped.get("latest") and scraped["latest"]["version"] == forge_version:
                    url = scraped["latest"]["url"]
            if not url:
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
        except Exception:
            url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"

        update_server_info(
            server_name, owner, "forge", server_version, "DOWNLOADING...",
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        try:
            jar_name = f"forge-{mc_version}-{forge_version}-installer.jar"
            success, message, _ = run_vanilla_download_container(
                server_name, server_version, url, jar_filename=jar_name, memory_mb=memory_mb
            )
            if not success:
                raise RuntimeError(message)
        except Exception as e:
            print(f"Failed to download Forge installer: {e}")
            import shutil
            shutil.rmtree(f"data/servers/{server_name}", ignore_errors=True)
            return "Failed to create server."

        # Update DB to the installer path
        installer_jar_path = f"data/servers/{server_name}/{jar_name}"
        update_server_info(
            server_name, owner, "forge", server_version, installer_jar_path,
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        print(f"Forge server '{server_name}' installer downloaded successfully.")
        return f"Server '{server_name}' created successfully."

    elif server_type.lower() == "neoforge":
        # Parse mc_version and neoforge_version from version e.g. "1.20.1-20.1.2"
        parts = server_version.split("-")
        if len(parts) == 2:
            mc_version, neoforge_version = parts[0], parts[1]
        else:
            mc_version = server_version
            try:
                from api.get.neoforge import get_neoforge_versions
                scraped = get_neoforge_versions(mc_version)
                if scraped.get("recommended"):
                    neoforge_version = scraped["recommended"]["version"]
                elif scraped.get("latest"):
                    neoforge_version = scraped["latest"]["version"]
                else:
                    raise ValueError("No neoforge version found.")
            except Exception:
                return f"Invalid version format '{server_version}' for NeoForge. Expected 'mc_version-neoforge_version' (e.g. 1.20.1-20.1.2)."

        # Try to find the installer URL
        try:
            from api.get.neoforge import get_neoforge_versions
            scraped = get_neoforge_versions(mc_version)
            url = None
            for v in scraped["versions"]:
                if v["version"] == neoforge_version:
                    url = v["url"]
                    break
            if not url:
                if scraped.get("recommended") and scraped["recommended"]["version"] == neoforge_version:
                    url = scraped["recommended"]["url"]
                elif scraped.get("latest") and scraped["latest"]["version"] == neoforge_version:
                    url = scraped["latest"]["url"]
            if not url:
                gav = "net/neoforged/forge" if "-" in neoforge_version else "net/neoforged/neoforge"
                url = f"https://maven.neoforged.net/releases/{gav}/{neoforge_version}/neoforge-{neoforge_version}-installer.jar"
        except Exception:
            gav = "net/neoforged/forge" if "-" in neoforge_version else "net/neoforged/neoforge"
            url = f"https://maven.neoforged.net/releases/{gav}/{neoforge_version}/neoforge-{neoforge_version}-installer.jar"

        update_server_info(
            server_name, owner, "neoforge", server_version, "DOWNLOADING...",
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        try:
            jar_name = f"neoforge-{neoforge_version}-installer.jar"
            success, message, _ = run_vanilla_download_container(
                server_name, server_version, url, jar_filename=jar_name, memory_mb=memory_mb
            )
            if not success:
                raise RuntimeError(message)
        except Exception as e:
            print(f"Failed to download NeoForge installer: {e}")
            import shutil
            shutil.rmtree(f"data/servers/{server_name}", ignore_errors=True)
            return "Failed to create server."

        # Update DB to the installer path
        installer_jar_path = f"data/servers/{server_name}/{jar_name}"
        update_server_info(
            server_name, owner, "neoforge", server_version, installer_jar_path,
            hostname=hostname,
            container_name=f"mc-{server_name}",
            memory_mb=memory_mb
        )

        print(f"NeoForge server '{server_name}' installer downloaded successfully.")
        return f"Server '{server_name}' created successfully."

    else:
        print(f"Server type '{server_type}' is not supported yet.")
    return


def run_forge_install_container(server_name, jar_filename, memory_mb=1024):
    """
    Run the Forge installer inside an ephemeral Docker container.
    """
    container_name = f"mc-install-{server_name}"
    image = f"eclipse-temurin:{DEFAULT_BUILD_JAVA}-jdk"
    
    client = docker.from_env()
    
    # Remove stale install container if exists
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass
        
    print(f"Starting install container ({image}) for Forge server '{server_name}'...")
    
    # Run the installer with --installServer
    command = (
        f'bash -c "'
        f"java -jar {jar_filename} --installServer 2>&1 | tee /data/creation.log && "
        f'chown -R 1000:1000 /data"'
    )
    
    log_path = os.path.join("data", "servers", server_name, "creation.log")
    
    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        detach=True,
        mounts=[server_data_mount(server_name)],
        working_dir="/data",
        mem_limit=f"{memory_mb}m",
        labels=get_compose_labels(f"install-{server_name}"),
    )
    
    stop_event = threading.Event()
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event, server_name),
        daemon=True,
    )
    log_thread.start()
    
    result = container.wait()
    exit_code = result.get("StatusCode", -1)
    
    stop_event.set()
    log_thread.join()
    
    try:
        logs = container.logs().decode("utf-8", errors="replace")
    except Exception:
        logs = ""
        
    try:
        container.remove()
    except Exception:
        pass
        
    if exit_code != 0:
        return False, f"Forge installation failed (exit {exit_code}):\n{logs}"
        
    return True, "Installation successful."


def install_forge(server_name):
    info = get_server_info(server_name)
    if not info:
        raise ValueError(f"Server '{server_name}' not found.")
        
    installer_path = info["jar_path"]
    jar_filename = os.path.basename(installer_path)
    
    # Update state in DB to INSTALLING...
    update_server_info(
        server_name, info["owner"], info["type"], info["version"], "INSTALLING...",
        hostname=info.get("hostname"),
        container_name=info.get("container_name"),
        memory_mb=info.get("memory_mb")
    )
    
    success, message = run_forge_install_container(server_name, jar_filename, memory_mb=2048)
    if not success:
        # Revert status back to INSTALL_REQUIRED
        update_server_info(
            server_name, info["owner"], info["type"], info["version"], installer_path,
            hostname=info.get("hostname"),
            container_name=info.get("container_name"),
            memory_mb=info.get("memory_mb")
        )
        raise RuntimeError(message)
        
    # Update jar_path in DB
    new_jar_path = installer_path.replace("-installer.jar", ".jar")
    update_server_info(
        server_name, info["owner"], info["type"], info["version"], new_jar_path,
        hostname=info.get("hostname"),
        container_name=info.get("container_name"),
        memory_mb=info.get("memory_mb")
    )
    
    # Write default eula.txt
    local_eula_path = os.path.join("data", "servers", server_name, "eula.txt")
    if not os.path.exists(local_eula_path):
        import time
        date_str = time.strftime("#%a %b %d %H:%M:%S UTC %Y")
        eula_content = (
            "#By changing the setting below to TRUE you are agreeing to the Minecraft EULA (https://aka.ms/MinecraftEULA).\n"
            f"{date_str}\n"
            "eula=false\n"
        )
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/eula.txt", eula_content)
        
    # Write default server.properties
    local_props_path = os.path.join("data", "servers", server_name, "server.properties")
    if not os.path.exists(local_props_path):
        server_props = (
            "server-port=25565\n"
            "enable-rcon=false\n"
            "rcon.password=admin\n"
            "rcon.port=25575\n"
            "online-mode=true\n"
        )
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/server.properties", server_props)
        
    return "Installation successful."
