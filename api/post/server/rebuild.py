import os
import re
import socket
import threading
import time
from mcrcon import MCRcon
from api.post.server.create import run_build_tools
from api.db import update_server_info
from api.get.server.console import get_server_version
from api.get.server.console import get_server_properties
from api.get.server.console import is_server_running

def rebuild_server(server_name):
    print(f"Rebuilding server '{server_name}'...")
    
    # 1. Detect info
    version = get_server_version(server_name)
    print(f"Detected version: {version}")
    
    # Assume Spigot for now as it's the only one with BuildTools logic implemented
    server_type = "spigot" 
    
    # 2. Stop server if running
    # We need RCON to stop it gracefully, or we can just kill the screen? 
    # Graceful is better.
    properties = get_server_properties(server_name)
    if properties and "rcon.port" in properties and "rcon.password" in properties:
        rcon_port = int(properties["rcon.port"])
        rcon_password = properties["rcon.password"]
        try:
            with MCRcon("localhost", rcon_password, rcon_port) as rcon:
                if is_server_running(rcon):
                    print("Server is running. Stopping it...")
                    rcon.command("stop")
                    time.sleep(5) # Give it time to save and close
        except Exception:
            pass # Maybe not running or rcon failed

    # Kill screen session just in case it's hung or didn't stop
    # os.system(f"screen -S {server_name} -X quit") 
    # Actually, let's rely on stop. If screen persists, run_build_tools might face file locking issues?
    # Usually stopping the java process closes the screen.
    
    # 3. Rebuild
    success, msg = run_build_tools(server_name, version)
    print(msg)
    
    if success:
        # 4. Update DB
        # Jar path: we know run_build_tools names it `spigot<BuildToolsVer>-<Ver>.jar`
        # But `run_build_tools` does the move.
        # We need to know the Exact jar name.
        # `get_server_version` reads detection from `start.sh`.
        # `run_build_tools` UPDATES `start.sh`? 
        # Wait, `run_build_tools` in `create.py` DOES NOT update `start.sh`.
        # `create_server` does.
        # So `run_build_tools` only REPLACES the file on disk.
        # So `start.sh` is still pointing to the file.
        # We can extract the jar name from `start.sh`.
        
        jar_path = ""
        try:
            with open(f"data/servers/{server_name}/start.sh", "r") as f:
                content = f.read()
                # Extract jar name
                match = re.search(r"-jar\s+(.*?\.jar)", content)
                if match:
                    jar_path = match.group(1)
        except Exception:
            pass
            
        full_jar_path = f"data/servers/{server_name}/{jar_path}"
        
        # Owner default "admin"
        update_server_info(server_name, "admin", server_type, version, full_jar_path)
        print("Server info updated in database.")
        
        return "Server rebuild complete and info saved."
    else:
        return "Server rebuild failed."
