import os
import subprocess

import api.get.lastbuildtoolsversion

import time
import threading

JAVAVERSION = "25"
JAVA = "/Library/Java/JavaVirtualMachines/jdk-" + JAVAVERSION + ".jdk/Contents/Home/bin/java"
BUILDTOOLSJAR = "BuildTools" + api.get.lastbuildtoolsversion.last_buildtools_version() + ".jar"

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

def create_server(server_name, server_type, server_version):
    print("creating server...")
    os.system("cd data/servers && mkdir " + server_name)
    
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
        os.system("cd data/servers/" + server_name + " && wget https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar")
        print("Downloaded BuildTools.jar successfully.")
        os.system(f"mv data/servers/{server_name}/BuildTools.jar data/servers/{server_name}/{BUILDTOOLSJAR}")

        log_path = f"data/servers/{server_name}/buildtools.log"
        stop_event = threading.Event()

        with open(log_path, "w") as log_file:
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

        with open(log_path, "r") as log_file:
            log_content = log_file.read()

        if "Success! Everything completed successfully." in log_content:
            os.remove(log_path)
            print(f"Spigot server '{server_name}' created successfully with version {server_version}.")
            return f"Server '{server_name}' created successfully."
        elif "*** The version you have requested to build requires Java versions between" in log_content:
            os.system("brew install --cask oracle-jdk@" + JAVAVERSION)
            return "Java version mismatch. Installed required Java version."
        else:
            print("Failed to build the Spigot server. See buildtools.log for details.")
            return "Failed to create server."

    # elif server_type.lower() == "paper":
    #     if "not found" in IsWgetInstalled.stdout:
    #         print("wget is not installed. Please install wget to proceed.")
    #         print('run "brew install wget" (macOS) or "sudo apt-get install wget" (Linux) to install wget')
    #         return "Failed to create server."
    #     else:
    #         os.system("cd data/servers/" + server_name + " && wget https://papermc.io/api/v2/projects/paper/versions/" + server_version + "/builds/" + server_version + "/downloads/paper-" + server_version + ".jar")
    #         print("Downloaded Paper.jar successfully.")

    else:
        print(f"Server type '{server_type}' is not supported yet.")
    return