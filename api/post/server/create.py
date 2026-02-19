import os
import subprocess

import api.get.lastbuildtoolsversion
from api.db import update_server_info

import time
import threading

JAVAVERSION = "25"
JAVA = "/Library/Java/JavaVirtualMachines/jdk-" + JAVAVERSION + ".jdk/Contents/Home/bin/java"
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
    max_retries = 3

    for attempt in range(max_retries):
        stop_event = threading.Event()

        # Ensure file is fresh
        with open(log_path, "w") as f:
            f.write("")

        # Keep file open during execution
        with open(log_path, "a") as log_file:
            process = subprocess.Popen(
                f"cd data/servers/{server_name} && {JAVA} -jar {BUILDTOOLSJAR} --rev {server_version}",
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
        time.sleep(0.5)

        with open(log_path, "r") as log_file:
            log_content = log_file.read()

        print(f"[Debug] Log content length: {len(log_content)}")

        if "Success! Everything completed successfully." in log_content:
            os.remove(log_path)
            os.system(f"mv data/servers/{server_name}/spigot-{server_version}.jar data/servers/{server_name}/spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar")
            return True, "Build successful."
        
        # Broaden the check
        failure_patterns = [
            "Connection timeout",
            "Could not resolve host",
            "Connection timed out",
            "Connection reset",
            "An error occurred: Connection timeout error"
        ]
        
        found_pattern = None
        for pattern in failure_patterns:
            if pattern in log_content:
                found_pattern = pattern
                break
        
        if found_pattern:
            if attempt < max_retries - 1:
                print(f"[Debug] Match found for error pattern: '{found_pattern}'")
                print(f"\n[System] BuildTools encountered a network error. Retrying... (Attempt {attempt+2}/{max_retries})\n")
                time.sleep(3)
                continue
        
        if "*** The version you have requested to build requires Java versions between" in log_content:
            os.system("brew install --cask oracle-jdk@" + JAVAVERSION)
            return False, "Java version mismatch. Installed required Java version."
        
        # Debug output if we fail without a known cause
        print(f"[Debug] Build failed. Return code: {return_code}")
        # print(f"[Debug] Log content excerpt: {log_content[-200:]}")
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
            os.system(f'echo "{JAVA} -Xmx{RAMUSAGE} -Xms{RAMUSAGE} -jar spigot{LASTBUILDTOOLSVERSION}-{server_version}.jar nogui" >> data/servers/{server_name}/start.sh')
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