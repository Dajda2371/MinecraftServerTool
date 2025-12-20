JAVAVERSION = "25"
JAVA = "/Library/Java/JavaVirtualMachines/jdk-" + JAVAVERSION + ".jdk/Contents/Home/bin/java"

import os
import subprocess

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

        TryBuildServer = subprocess.run(
            f"cd data/servers/{server_name} && {JAVA} -jar BuildTools.jar --rev {server_version}",
            capture_output=True,
            text=True,
            shell=True
        )

        if "Success! Everything completed successfully." in TryBuildServer.stdout:
            print(f"Spigot server '{server_name}' created successfully with version {server_version}.")
            return f"Server '{server_name}' created successfully."
        elif "*** The version you have requested to build requires Java versions between" in TryBuildServer.stdout:
            os.system("brew install --cask oracle-jdk@" + JAVAVERSION)
        else:
            print("Failed to build the Spigot server. Please check if Java is installed and the version is correct.")
            return "Failed to create server."

        print(f"Spigot server '{server_name}' created with version {server_version}.")

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