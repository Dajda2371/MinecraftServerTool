import api.get.helloworld
import api.get.server.console

import api.post.server.create
import api.post.server.run

USER = "Admin"
QUITCMD = ['q', 'quit', 'back', 'return']

def ApiGetHelloWorld():
    api.get.helloworld.hello_world()

def ApiPostServerCreate(cmd):
        args = cmd[len("server create "):].strip().split()
        if len(args) != 3:
            while len(args) != 3:
                server_name = input("Enter server name: ").strip()
                if server_name == '':
                    print("Server name cannot be empty.")
                    continue

                server_type = input("Enter server type: ").strip()
                if server_type == '':
                    print("Server type cannot be empty.")
                    continue

                server_version = input("Enter server version: ").strip()
                if server_version == '':
                    print("Server version cannot be empty.")
                    continue

                args = [server_name, server_type, server_version]
        else:
            server_name, server_type, server_version = args
        response = api.post.server.create.create_server(server_name, server_type, server_version)
        return print(f"Server created: {response}")

def ApiGetServerConsole(cmd):
    args = cmd[len("server console "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            server_name = input("Enter server name for console: ").strip()
            if server_name == '':
                print("Server name cannot be empty.")
                continue
            args = [server_name]
    else:
        server_name = args[0]
    api.get.server.console.interactive_console(server_name)

def ApiPostServerRun(cmd):
    args = cmd[len("server run "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            server_name = input("Enter server name to run: ").strip()
            if server_name == '':
                print("Server name cannot be empty.")
                continue
            args = [server_name]
    else:
        server_name = args[0]
    response = api.post.server.run.run_server(server_name)
    return print(f"Server run response: {response}")

while True:
    try:
        cmd = input(USER + ">> ")
        if cmd.lower() == 'exit':
            print("Exiting the program.")
            break

        elif cmd.strip() == '':
            continue

        elif cmd == "help":
            print("Available commands:")
            print("  helloworld               - Get a hello world message")
            print("  server create <name> <ip> - Create a new server")
            print("  server                   - Enter server command mode")
            print("  help                     - Show this help message")
            print("  exit                     - Exit the program")

        elif cmd.lower() == "helloworld":
            ApiGetHelloWorld()

        elif cmd.startswith("server"):
            if cmd =="server":
                while True:
                    cmd_server = input(USER + "/Server>> ")
                    if cmd_server.lower() in QUITCMD:
                        break
                    elif cmd_server.strip() == '':
                        continue
                    elif cmd_server.startswith("create"):
                        ApiPostServerCreate("server " + cmd_server)
                    elif cmd_server.startswith("run"):
                        ApiPostServerRun("server " + cmd_server)
                    # elif cmd_server.startswith("stop"):
                    #     ApiPostServerStop("server " + cmd_server)
                    # elif cmd_server.startswith("restart"):
                    #     ApiPostServerRestart("server " + cmd_server)
                    # elif cmd_server.startswith("status"):
                    #     ApiGetServerStatus("server " + cmd_server)
                    elif cmd_server.startswith("console"):
                        ApiGetServerConsole("server " + cmd_server)
                    else:
                        print("Invalid server command. Type 'back' to return.")

            elif cmd.startswith("server create"):
                ApiPostServerCreate(cmd)

            elif cmd.startswith("server run"):
                ApiPostServerRun(cmd)

            elif cmd.startswith("server console"):
                ApiGetServerConsole(cmd)

            else:
                print("Invalid server command. Type 'help' for a list of commands.")

        else:
            print("Invalid command. Please try again.")
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting.")
        break
    except Exception as e:
        print(f"An error occurred: {e}")
        break