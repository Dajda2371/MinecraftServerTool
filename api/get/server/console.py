import os
import subprocess
import threading
import time
import readline
import sys

def follow_log_file(path, stop_event, prompt="> "):
    try:
        with open(path, "r") as f:
            f.seek(0, 2)
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    # Move to new line, print log, then redraw clean prompt
                    sys.stdout.write("\r")
                    sys.stdout.write(line)
                    sys.stdout.write(prompt)
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
    except FileNotFoundError:
        print(f"(log file not found yet: {path})")

def interactive_console(server_name):
    if not is_server_running(server_name):
        print(f"Server '{server_name}' is not running.")
        return

    # Prefer Minecraft latest.log, fallback to screen log
    mc_log = f"data/servers/{server_name}/logs/latest.log"
    screen_log = "screenlog.0"
    log_path = mc_log if os.path.exists(mc_log) else screen_log

    # Clear any previous readline state (prevents echoing outer CLI commands)
    readline.clear_history()

    stop_event = threading.Event()
    log_thread = threading.Thread(
        target=follow_log_file,
        args=(log_path, stop_event, "> "),
        daemon=True
    )
    log_thread.start()

    print(f"Connected to server '{server_name}'. Type 'quit' to exit.")
    print(f"Streaming logs from: {log_path}")

    try:
        while True:
            command = input("> ").strip()

            if command.lower() == "quit":
                print("Console closed.")
                break

            if command:
                send_server_command(server_name, command)
    except (EOFError, KeyboardInterrupt):
        print("\nExiting console.")
    finally:
        stop_event.set()
        log_thread.join()

def is_server_running(server_name):
    # Most reliable: exits 0 if the session exists
    probe = subprocess.run(
        ["screen", "-S", server_name, "-Q", "select", "."],
        capture_output=True,
        text=True
    )
    if probe.returncode == 0:
        return True

    # Fallback: parse screen list output (stdout or stderr depending on build)
    listing = subprocess.run(
        ["screen", "-list"],
        capture_output=True,
        text=True
    )
    combined = (listing.stdout or "") + "\n" + (listing.stderr or "")

    # Typical lines look like: "12345.MyServer\t(Detached)"
    for line in combined.splitlines():
        if f".{server_name}" in line or line.strip().endswith(f".{server_name}") or f"\t{server_name}\t" in line:
            return True

    return False

def send_server_command(server_name, command):
    escaped_command = command.replace('"', '\\"')

    os.system(
        f'screen -S {server_name} -X stuff "{escaped_command}\n"'
    )

    return f"Command sent to server '{server_name}': {command}"