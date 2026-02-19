import api.get.helloworld
import api.get.server.console
import api.get.server.owner.list
import api.get.user.list

import api.post.server.create
import api.post.server.rebuild
import api.post.server.run
import api.post.server.owner
import api.post.user.create
import api.post.user.delete

USER = "Admin"
QUITCMD = ['q', 'quit', 'back', 'return']

def ApiGetHelloWorld():
    api.get.helloworld.hello_world()

def ApiPostServerRebuild(cmd):
    args = cmd[len("server rebuild "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            server_name = input("Enter server name to rebuild: ").strip()
            if server_name == '':
                print("Server name cannot be empty.")
                continue
            args = [server_name]
    else:
        server_name = args[0]
    response = api.post.server.rebuild.rebuild_server(server_name)
    return print(f"Server rebuild response: {response}")

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
        response = api.post.server.create.create_server(server_name, server_type, server_version, owner=USER)
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

def ApiPostUserCreate(cmd):
    args = cmd[len("user create "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            username = input("Enter username: ").strip()
            if username == '':
                print("Username cannot be empty.")
                continue
            args = [username]
    else:
        username = args[0]
    
    response = api.post.user.create.create_user(username)
    return print(f"User create response: {response}")

def ApiPostUserDelete(cmd):
    args = cmd[len("user delete "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            username = input("Enter username to delete: ").strip()
            if username == '':
                print("Username cannot be empty.")
                continue
            args = [username]
    else:
        username = args[0]
    
    response = api.post.user.delete.delete_user(username)
    return print(f"User delete response: {response}")

def ApiGetUserList():
    print(api.get.user.list.list_users())

def ApiPostServerOwner(cmd):
    # Expected cmd format: "server owner <server_name> <username>"
    args = cmd[len("server owner "):].strip().split()
    if len(args) != 2:
        print("Usage: server owner <server_name> <username>")
        return

    server_name, username = args
    response = api.post.server.owner.update_owner(server_name, username)
    print(f"Server owner update response: {response}")

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
            print("  server rebuild <name>    - Rebuild a server and update info")
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
                    elif cmd_server.startswith("rebuild"):
                        ApiPostServerRebuild("server " + cmd_server)
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
                    elif cmd_server.startswith("owner"):
                        if cmd_server == "owner":
                            while True:
                                cmd_owner = input(USER + "/Server/Owner>> ")
                                if cmd_owner.lower() in QUITCMD:
                                    break
                                elif cmd_owner.strip() == '':
                                    continue
                                else:
                                    # User types "<server> <username>"
                                    ApiPostServerOwner("server owner " + cmd_owner)
                        
                        elif cmd_server.startswith("owner"):
                             # cmd_server is "owner <server> <username>"
                             ApiPostServerOwner("server " + cmd_server)
                    else:
                        print("Invalid server command. Type 'back' to return.")

            elif cmd.startswith("server create"):
                ApiPostServerCreate(cmd)
            
            elif cmd.startswith("server rebuild"):
                ApiPostServerRebuild(cmd)

            elif cmd.startswith("server run"):
                ApiPostServerRun(cmd)

            elif cmd.startswith("server console"):
                ApiGetServerConsole(cmd)

            elif cmd.startswith("server owner"):
                if cmd == "server owner":
                    while True:
                        cmd_owner = input(USER + "/Server/Owner>> ")
                        if cmd_owner.lower() in QUITCMD:
                            break
                        elif cmd_owner.strip() == '':
                            continue
                        else:
                             ApiPostServerOwner("server owner " + cmd_owner)
                else:
                    ApiPostServerOwner(cmd)

            else:
                print("Invalid server command. Type 'help' for a list of commands.")

        elif cmd.startswith("user"):
            if cmd == "user":
                while True:
                    cmd_user = input(USER + "/User>> ")
                    if cmd_user.lower() in QUITCMD:
                        break
                    elif cmd_user.strip() == '':
                        continue
                    elif cmd_user.startswith("create"):
                        ApiPostUserCreate("user " + cmd_user)
                    elif cmd_user.startswith("delete"):
                        ApiPostUserDelete("user " + cmd_user)
                    elif cmd_user.startswith("list"):
                        ApiGetUserList()
                    else:
                        print("Invalid user command. Type 'back' to return.")

            elif cmd.startswith("user create"):
                ApiPostUserCreate(cmd)

            elif cmd.startswith("user delete"):
                ApiPostUserDelete(cmd)

            elif cmd.startswith("user list"):
                ApiGetUserList()

            else:
                print("Invalid user command. Type 'help' for a list of commands.")

        else:
            print("Invalid command. Please try again.")
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting.")
        break
    except Exception as e:
        print(f"An error occurred: {e}")
        break