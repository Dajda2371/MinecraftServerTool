import os

RAMUSAGE = "1024M"

def run_server(server_name):
    os.system("chmod +x data/servers/" + server_name + "/start.sh")
    os.system(f"screen -dmS {server_name} bash -c 'cd data/servers/{server_name} && ./start.sh'")
    return f"Server '{server_name}' is starting in a detached screen session."

# def run_server(server_name):
    # server_dir = f"data/servers/{server_name}"
    # log_file = f"{server_dir}/server.log"

    # cmd = (
    #     f"screen -dmS {server_name} bash -c "
    #     f"'cd {server_dir} || exit 1; "
    #     f"java -Xmx{RAMUSAGE} -Xms{RAMUSAGE} -jar server.jar nogui "
    #     f"2>&1 | tee -a server.log; "
    #     f"exec bash'"
    # )

    # os.system(cmd)
    # return f"Server '{server_name}' attempted to start in a detached screen session."