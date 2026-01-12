import os
import re
import socket
import threading
import time
import _thread
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
    
    current_file = None
    current_inode = None

    while not stop_event.is_set():
        try:
            if current_file is None:
                if os.path.exists(path):
                    current_file = open(path, "r")
                    current_inode = os.fstat(current_file.fileno()).st_ino
                else:
                    time.sleep(1)
                    continue

            line = current_file.readline()
            if line:
                print(line, end="")
                if rcon_ready_event and not rcon_ready_event.is_set():
                    if "RCON running on" in line and str(rcon_port) in line:
                        rcon_ready_event.set()
                
                if "ThreadedAnvilChunkStorage: All dimensions are saved" in line:
                    if not stop_event.is_set():
                        # Server closed the RCON connection
                        print("\n[RCON connection stopped by server. Quitting...]")
                        _thread.interrupt_main()
                        return
            else:
                # No new line, check for rotation
                try:
                    if os.path.exists(path):
                        new_inode = os.stat(path).st_ino
                        if new_inode != current_inode:
                            # File rotated
                            print(f"\n[Log rotated detected. Reopening {path}...]\n")
                            current_file.close()
                            current_file = None
                            current_inode = None
                            # Reset event because previous RCON signal might be from old file
                            if rcon_ready_event:
                                rcon_ready_event.clear()
                            continue
                except FileNotFoundError:
                    pass # path might have disappeared momentarily
                
                time.sleep(0.3)

        except Exception as e:
            print(f"\n[Error follow_log_file: {e}]\n")
            if current_file:
                current_file.close()
            break
    
    if current_file:
        current_file.close()

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
        
        while not stop_event.is_set():
            # Wait for the signal
            while not rcon_ready_event.is_set() and not stop_event.is_set():
                time.sleep(0.5)
            
            if stop_event.is_set():
                break

            # Try connecting
            try:
                with MCRcon("localhost", rcon_password, rcon_port) as rcon:
                    if not is_server_running(rcon):
                        # Could be phantom positive or server died immediately
                        print(f"Server '{server_name}' reachable but returned error on list command. Retrying...")
                        rcon_ready_event.clear()
                        # Give it a moment before retry
                        time.sleep(1)
                        continue

                    print(f"Connected to server '{server_name}' via RCON. Type 'quit' to exit.")

                    session = PromptSession()
                    with patch_stdout():
                        while True:
                            if not is_server_running(rcon):
                                print(f"Server '{server_name}' has stopped. Exiting console.")
                                return # Exit completely
                            try:
                                command = session.prompt("> ")
                                if command.lower() == "quit":
                                    print("Console closed.")
                                    return # Exit completely
                                if command:
                                    response = rcon.command(command)
                                    if response:
                                        print(response)
                            except (EOFError, KeyboardInterrupt):
                                print("\nExiting console.")
                                return # Exit completely
            except ConnectionRefusedError:
                # This often happens if we read a STALE log file that said "RCON ready" 
                # but the actual server is not listening (or dead).
                # We should clear the event and wait for a NEW signal (likely from log rotation).
                # OR we should retry delicately if we think it's just startup lag.
                # But typically "RCON running" msg comes AFTER bind.
                # So refusal means stale log.
                # print(f"[Connection Refused] Stale log entry detected? Waiting for fresh signal...")
                rcon_ready_event.clear()
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        stop_event.set()
        log_thread.join()
