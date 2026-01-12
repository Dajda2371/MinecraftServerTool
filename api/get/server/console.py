import os
import re
import socket
import threading
import time
from mcrcon import MCRcon
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

def get_server_properties(server_name):
    properties = {}
    path = f"data/servers/{server_name}/server.properties"
    try:
        with open(path, "r") as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    properties[key] = value
    except FileNotFoundError:
        return None
    return properties

def follow_log_file(path, stop_event, rcon_ready_event, rcon_port):
    print(f"Streaming logs from: {path}")
    file_opened = False
    
    while not stop_event.is_set():
        try:
            with open(path, "r") as f:
                file_opened = True
                while not stop_event.is_set():
                    line = f.readline()
                    if line:
                        print(line, end="")
                        if rcon_ready_event and not rcon_ready_event.is_set():
                            if "RCON running on" in line and str(rcon_port) in line:
                                rcon_ready_event.set()
                    else:
                        time.sleep(0.3)
        except FileNotFoundError:
            if not file_opened:
                time.sleep(1)
            else:
                # If file was opened but now is gone, maybe server restarted/log rotated?
                # We try to reopen.
                time.sleep(1)
        except Exception:
            break

def is_server_running(rcon):
    try:
        rcon.command("list")
        return True
    except (socket.error, ConnectionRefusedError):
        return False

def interactive_console(server_name):
    properties = get_server_properties(server_name)
    if not properties or "rcon.port" not in properties or "rcon.password" not in properties:
        print(f"RCON is not configured for server '{server_name}'.")
        return

    rcon_port = int(properties["rcon.port"])
    rcon_password = properties["rcon.password"]
    log_path = f"data/servers/{server_name}/logs/latest.log"

    stop_event = threading.Event()
    rcon_ready_event = threading.Event()
    
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event, rcon_ready_event, rcon_port),
        daemon=True
    )
    log_thread.start()

    try:
        print(f"Waiting for RCON to start on port {rcon_port}...")
        while not rcon_ready_event.is_set():
            time.sleep(0.5)

        with MCRcon("localhost", rcon_password, rcon_port) as rcon:
            if not is_server_running(rcon):
                print(f"Server '{server_name}' is not running.")
                return

            print(f"Connected to server '{server_name}' via RCON. Type 'quit' to exit.")

            session = PromptSession()

            try:
                with patch_stdout():
                    while True:
                        if not is_server_running(rcon):
                            print(f"Server '{server_name}' has stopped. Exiting console.")
                            break
                        try:
                            command = session.prompt("> ")
                            if command.lower() == "quit":
                                print("Console closed.")
                                break
                            if command:
                                response = rcon.command(command)
                                if response:
                                    print(response)
                        except (EOFError, KeyboardInterrupt):
                            print("\nExiting console.")
                            break
            except Exception as e:
                print(f"Console error: {e}")
    except ConnectionRefusedError:
        print(f"RCON connection to '{server_name}' was refused. Is the server running?")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        stop_event.set()
        log_thread.join()
