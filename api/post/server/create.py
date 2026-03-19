import os
import subprocess
import platform
import re
import requests
import tarfile
import shutil

import api.get.lastbuildtoolsversion
from api.db import update_server_info

import time
import threading

JAVAVERSION = "25"

def get_arch():
    machine = platform.machine().lower()
    if "arm64" in machine or "aarch64" in machine:
        return "aarch64"
    return "x64"

def get_local_java_path(server_name):
    # Search for java executable in the local jdk directory
    jdk_dir = os.path.join("data", "servers", server_name, "jdk")
    if not os.path.exists(jdk_dir):
        return None
    
    for root, dirs, files in os.walk(jdk_dir):
        if "java" in files:
            path = os.path.join(root, "java")
            if os.access(path, os.X_OK):
                return path
    return None

def install_local_java(server_name, version):
    print(f"Installing Java {version} locally for server '{server_name}'...")
    arch = get_arch()
    os_name = platform.system().lower()
    if os_name == "darwin":
        os_name = "mac"
    elif os_name != "linux":
        # Fallback for others, but Adoptium supports mac, linux, windows, solaris, aix
        pass 
    
    # Use Adoptium API to get the latest download link
    api_url = f"https://api.adoptium.net/v3/binary/latest/{version}/ga/{os_name}/{arch}/jdk/hotspot/normal/eclipse"
    
    jdk_dir = os.path.join("data", "servers", server_name, "jdk")
    if os.path.exists(jdk_dir):
        shutil.rmtree(jdk_dir)
    os.makedirs(jdk_dir, exist_ok=True)
    
    tar_path = os.path.join("data", "servers", server_name, "jdk.tar.gz")
    
    try:
        print(f"Downloading JDK from {api_url}...")
        response = requests.get(api_url, stream=True, allow_redirects=True)
        response.raise_for_status()
        with open(tar_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print("Extracting JDK...")
        # Use tar command for extraction as it handles Mac's metadata and symlinks better
        subprocess.run(["tar", "-xzf", tar_path, "-C", jdk_dir], check=True)
        os.remove(tar_path)
        
        java_path = get_local_java_path(server_name)
        if java_path:
            # On Linux/Unix, ensure it's executable (usually happens with tar, but let's be safe)
            os.chmod(java_path, 0o755)
            print(f"Java {version} installed successfully at {java_path}")
            return java_path
        else:
            print("Failed to find java executable after extraction.")
            return None
    except Exception as e:
        print(f"Error installing local Java: {e}")
        return None

def get_java_executable(server_name):
    local_java = get_local_java_path(server_name)
    if local_java:
        return local_java
    
    # If no local Java is found, install the default version into the server directory
    new_java = install_local_java(server_name, JAVAVERSION)
    if not new_java:
        raise Exception(f"Failed to find or install local Java for server '{server_name}'. System-wide Java is disabled.")
    return new_java

LASTBUILDTOOLSVERSION = api.get.lastbuildtoolsversion.last_buildtools_version()
BUILDTOOLSJAR = "BuildTools" + LASTBUILDTOOLSVERSION + ".jar"
RAMUSAGE = "1024M"

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

def run_build_tools(server_name, server_version):
    target_jar = f"data/servers/{server_name}/{BUILDTOOLSJAR}"
    unversioned_jar = f"data/servers/{server_name}/BuildTools.jar"
    
    if os.path.exists(target_jar):
        print(f"found existing {BUILDTOOLSJAR}, skipping download")
    elif os.path.exists(unversioned_jar):
        print(f"found existing BuildTools.jar, renaming to {BUILDTOOLSJAR}")
        os.rename(unversioned_jar, target_jar)
    else:
        # Use -O to save directly to the target filename, avoiding conflicts
        os.system(f"cd data/servers/{server_name} && wget -O {BUILDTOOLSJAR} https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar")
        print("Downloaded BuildTools.jar successfully.")

    log_path = f"data/servers/{server_name}/buildtools.log"
    max_retries = 5

    for attempt in range(max_retries):
        stop_event = threading.Event()
        current_java = get_java_executable(server_name)

        # Ensure file is fresh
        with open(log_path, "w") as f:
            f.write("")

        # Keep file open during execution
        with open(log_path, "a") as log_file:
            print(f"Running BuildTools with Java: {current_java}")
            process = subprocess.Popen(
                f"cd data/servers/{server_name} && {current_java} -jar {BUILDTOOLSJAR} --rev {server_version}",
                stdout=log_file,
                stderr=subprocess.STDOUT,
                shell=True
            )

            log_thread = threading.Thread(
                target=follow_log_file,
                args=(log_path, stop_event),
                daemon=True
            )
            log_thread.start()

            return_code = process.wait()
            stop_event.set()
            log_thread.join()

        # Small buffer time for FS flush
        time.sleep(1)

        with open(log_path, "r") as log_file:
            log_content = log_file.read()

        print(f"[Debug] Build attempt {attempt+1} finished. Return code: {return_code}. Log length: {len(log_content)}")

        if "Success! Everything completed successfully." in log_content:
            os.remove(log_path)
            os.system(f"mv data/servers/{server_name}/spigot-{server_version}.jar data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar")
            return True, "Build successful."
        
        # Check for Java version mismatch
        # Example: *** The version you have requested to build requires Java versions between [Java 21, Java 25], but you are using Java 17
        mismatch_match = re.search(r"requires Java versions between \[Java (\d+), Java (\d+)\]", log_content)
        if mismatch_match:
            required_min = mismatch_match.group(1)
            required_max = mismatch_match.group(2)
            print(f"Java version mismatch detected. Required: {required_min}-{required_max}")
            
            # We'll install the maximum supported version within the range
            new_java_path = install_local_java(server_name, required_max)
            if new_java_path:
                print(f"Retrying build with new local Java: {new_java_path}")
                continue
            else:
                return False, f"Failed to install required Java {required_max}."

        # Broaden the check
        failure_patterns = [
            "connection timeout",
            "could not resolve host",
            "connection timed out",
            "connection reset",
            "timeout",
            "failed to connect",
            "error occurred: connection timeout error"
        ]
        
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
        
        # Debug output if we fail without a known cause
        print(f"[Debug] Build failed. Return code: {return_code}")
        break

    print("Failed to build the Spigot server. See buildtools.log for details.")
    return False, "Failed to create server."

def create_server(server_name, server_type, server_version, owner="admin"):
    print("creating server...")
    os.makedirs(f"data/servers/{server_name}", exist_ok=True)
    
    IsWgetInstalled = subprocess.run(
        ["which", "wget"],
        capture_output=True,
        text=True
    )
    
    if "not found" in IsWgetInstalled.stdout:
        print("wget is not installed. Please install wget to proceed.")
        print('run "brew install wget" (macOS) or "sudo apt-get install wget" (Linux) to install wget')
        return "Failed to create server."
    
    if server_type.lower() == "vanilla":
        # os.system("cd data/servers/" + server_name + " && wget https://launcher.mojang.com/v1/objects/" + server_version + "/server.jar")
        # print(f"Vanilla server '{server_name}' created with version {server_version}.")
        # return f"Server '{server_name}' created successfully."
        print("Vanilla server creation is not implemented yet.")
        return "Failed to create server."

    elif server_type.lower() == "spigot":
        success, message = run_build_tools(server_name, server_version)
        if success:
            current_java = get_java_executable(server_name)
            os.system(f'echo "{current_java} -Xmx{RAMUSAGE} -Xms{RAMUSAGE} -jar spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar nogui" >> data/servers/{server_name}/start.sh')
            os.system(f'echo "eula=true" > data/servers/{server_name}/eula.txt')
            os.system(f'echo "enable-rcon=true\nrcon.password=admin\nrcon.port=25575" > data/servers/{server_name}/server.properties')
            
            full_jar_path = f"data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar"
            update_server_info(server_name, owner, "spigot", server_version, full_jar_path)
            
            print(f"Spigot server '{server_name}' created successfully with version {server_version}.")
            return f"Server '{server_name}' created successfully."
        else:
            return message

    # elif server_type.lower() == "paper":
    #     if "not found" in IsWgetInstalled.stdout:
    #         print("wget is not installed. Please install wget to proceed.")
    #         print('run "brew install wget" (macOS) or "sudo apt-get install wget" (Linux) to install wget')
    #         return "Failed to create server."
    #     else:
    #         os.system("cd data/servers/" + server_name + " && wget https://papermc.io/api/v2/projects/paper/versions/" + server_version + "/builds/" + server_version + "/downloads/paper-" + server_version + ".jar")
    #         print("Downloaded Paper.jar successfully.")
    # 
    else:
        print(f"Server type '{server_type}' is not supported yet.")
    return