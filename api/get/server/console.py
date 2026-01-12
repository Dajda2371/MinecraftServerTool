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

def follow_log_file(path, stop_event):
    try:
        with open(path, "r") as f:
            f.seek(0, 2)
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.3)
    except FileNotFoundError:
        print(f"(log file not found yet: {path})")

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

    animation = "|/-\\"
    for i in range(30):
        time.sleep(1)
        print(f"Connecting to server... {animation[i % len(animation)]}", end="\r")

    try:
        with MCRcon("localhost", rcon_password, rcon_port) as rcon:
            if not is_server_running(rcon):
                print(f"Server '{server_name}' is not running.")
                return

            log_path = f"data/servers/{server_name}/logs/latest.log"
            stop_event = threading.Event()
            log_thread = threading.Thread(
                target=follow_log_file,
                args=(log_path, stop_event),
                daemon=True
            )
            log_thread.start()

            print(f"Connected to server '{server_name}' via RCON. Type 'quit' to exit.")
            print(f"Streaming logs from: {log_path}")

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
            finally:
                stop_event.set()
                log_thread.join()
    except ConnectionRefusedError:
        print(f"RCON connection to '{server_name}' was refused. Is the server running?")
