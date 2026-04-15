import os
import re
import time
import threading

import docker
import requests

import api.get.lastbuildtoolsversion
from api.db import update_server_info

LASTBUILDTOOLSVERSION = api.get.lastbuildtoolsversion.last_buildtools_version()
BUILDTOOLSJAR = "BuildTools" + LASTBUILDTOOLSVERSION + ".jar"
DEFAULT_BUILD_JAVA = "21"

VANILLA_GIST_URL = "https://gist.githubusercontent.com/cliffano/77a982a7503669c3e1acb0a0cf6127e9/raw/minecraft-server-jar-downloads.md"


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


def run_vanilla_download_container(server_name, version, jar_url, memory_mb=512):
    """
    Download the vanilla server JAR inside an ephemeral Docker container with
    the server's data folder bind-mounted at /data. Mirrors the pattern used
    by run_build_tools_container so all "create/build" work happens in a
    sidecar container, never in the management container.

    Returns (success, message, jar_filename).
    """
    host_data_path = os.getenv("MC_HOST_DATA_DIR", os.path.abspath("data"))
    server_host_path = os.path.join(host_data_path, "servers", server_name)
    container_name = f"mc-download-{server_name}"
    image = f"eclipse-temurin:{DEFAULT_BUILD_JAVA}-jdk"
    jar_filename = f"vanilla-{version}.jar"

    client = docker.from_env()

    # Remove stale download container if exists
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    print(f"Starting download container ({image}) for vanilla server '{server_name}' version {version}...")

    command = (
        f'bash -c "'
        f"apt-get update -qq && apt-get install -y -qq curl && "
        f"curl -fsSL -o /data/{jar_filename} '{jar_url}' && "
        f'chown -R 1000:1000 /data"'
    )

    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        detach=True,
        volumes={server_host_path: {"bind": "/data", "mode": "rw"}},
        working_dir="/data",
        mem_limit=f"{memory_mb}m",
    )

    result = container.wait()
    exit_code = result.get("StatusCode", -1)

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


def follow_log_file(path, stop_event):
    try:
        with open(path, "r") as f:
            f.seek(0, 2)  # move to end of file
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    print(line, end="")
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
    host_data_path = os.getenv("MC_HOST_DATA_DIR", os.path.abspath("data"))
    server_host_path = os.path.join(host_data_path, "servers", server_name)
    maven_cache_path = os.path.join(host_data_path, ".buildtools-cache", "m2")
    repo_cache_path = os.path.join(host_data_path, ".buildtools-cache", "repos")
    os.makedirs(maven_cache_path, exist_ok=True)
    os.makedirs(repo_cache_path, exist_ok=True)
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
        volumes={
            server_host_path: {"bind": "/data", "mode": "rw"},
            maven_cache_path: {"bind": "/root/.m2", "mode": "rw"},
            repo_cache_path: {"bind": "/cache", "mode": "rw"},
        },
        environment={
            "MAVEN_OPTS": f"-Xmx{java_heap}m",
        },
        working_dir="/data",
        mem_limit=f"{memory_mb}m",
    )

    # Follow build log in real time
    stop_event = threading.Event()
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event),
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
        hostname: Optional hostname for Velocity routing (e.g., "survival.mc.davidbenes.cz")
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

    # Generate Velocity forwarding secret
    from api.db import generate_forwarding_secret
    forwarding_secret = generate_forwarding_secret()

    if server_type.lower() == "vanilla":
        update_server_info(
            server_name, owner, "vanilla", server_version, "DOWNLOADING...",
            hostname=hostname,
            container_name=f"mc-{server_name}",
            forwarding_secret=forwarding_secret,
            memory_mb=memory_mb
        )

        try:
            jar_name = download_vanilla_jar(server_name, server_version)
        except Exception as e:
            print(f"Failed to download vanilla JAR: {e}")
            return "Failed to create server."

        os.system(f'echo "eula=true" > data/servers/{server_name}/eula.txt')

        server_props = (
            "server-port=25565\n"
            "enable-rcon=true\n"
            "rcon.password=admin\n"
            "rcon.port=25575\n"
            "online-mode=false\n"
        )
        with open(f"data/servers/{server_name}/server.properties", "w") as f:
            f.write(server_props)

        full_jar_path = f"data/servers/{server_name}/{jar_name}"
        container_name = f"mc-{server_name}"

        update_server_info(
            server_name, owner, "vanilla", server_version, full_jar_path,
            hostname=hostname,
            container_name=container_name,
            forwarding_secret=forwarding_secret,
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
            forwarding_secret=forwarding_secret,
            memory_mb=memory_mb
        )

        success, message = run_build_tools(server_name, server_version, memory_mb=memory_mb)
        if success:
            os.system(f'echo "eula=true" > data/servers/{server_name}/eula.txt')

            # Write server.properties with online-mode=false for Velocity
            server_props = (
                "server-port=25565\n"
                "enable-rcon=true\n"
                "rcon.password=admin\n"
                "rcon.port=25575\n"
                "online-mode=false\n"
            )
            with open(f"data/servers/{server_name}/server.properties", "w") as f:
                f.write(server_props)

            # Write Velocity modern forwarding config
            paper_config_dir = f"data/servers/{server_name}/config"
            os.makedirs(paper_config_dir, exist_ok=True)
            paper_global = (
                "proxies:\n"
                "  velocity:\n"
                "    enabled: true\n"
                "    online-mode: true\n"
                f'    secret: "{forwarding_secret}"\n'
            )
            with open(f"{paper_config_dir}/paper-global.yml", "w") as f:
                f.write(paper_global)

            full_jar_path = f"data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar"
            container_name = f"mc-{server_name}"

            update_server_info(
                server_name, owner, "spigot", server_version, full_jar_path,
                hostname=hostname,
                container_name=container_name,
                forwarding_secret=forwarding_secret,
                memory_mb=memory_mb,
            )

            print(f"Spigot server '{server_name}' created successfully with version {server_version}.")
            print(f"  Hostname: {hostname}")
            print(f"  Container: {container_name}")
            print(f"  Online-mode: false (Velocity handles auth)")
            return f"Server '{server_name}' created successfully."
        else:
            return message

    else:
        print(f"Server type '{server_type}' is not supported yet.")
    return
