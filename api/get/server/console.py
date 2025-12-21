import os
import subprocess

def interactive_console(server_name):
    if not is_server_running(server_name):
        print(f"Server '{server_name}' is not running.")
        return

    print(f"Connected to server '{server_name}'. Type 'quit' to exit.")

    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting console.")
            break

        if command.lower() == "quit":
            print("Console closed.")
            break

        if command:
            send_server_command(server_name, command)

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