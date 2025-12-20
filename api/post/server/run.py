import os

RAMUSAGE = "1024M"

def run_server(server_name):
    os.system(f"screen -dmS {server_name} bash -c 'cd servers/{server_name} && java -Xmx{RAMUSAGE} -Xms{RAMUSAGE} -jar server.jar nogui'")
    return f"Server '{server_name}' is starting in a detached screen session." 