import api.get.helloworld

import api.post.server.create

USER = "Admin"
QUITCMD = ['q', 'quit', 'back', 'return']

def ApiGetHelloWorld():
    api.get.helloworld.helloworld()

def ApiPostServerCreate(cmd):
        args = cmd[len("server create "):].strip().split()
        if len(args) != 2:
            while len(args) != 2:
                server_name = input("Enter server name: ").strip()
                if server_name == '':
                    print("Server name cannot be empty.")
                    continue
                server_ip = input("Enter server IP: ").strip()
                if server_ip == '':
                    print("Server IP cannot be empty.")
                    continue
                args = [server_name, server_ip]
        else:
            server_name, server_ip = args
        response = api.post.server.create.create_server(server_name, server_ip)
        return print(f"Server created: {response}")

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
                    else:
                        print("Invalid server command. Type 'back' to return.")

            elif cmd.startswith("server create"):
                ApiPostServerCreate(cmd)
            
        else:
            print("Invalid command. Please try again.")
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting.")
        break
    except Exception as e:
        print(f"An error occurred: {e}")
        break