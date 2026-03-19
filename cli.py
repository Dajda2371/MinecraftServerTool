import api.get.helloworld
import api.get.server.console
import api.get.user.list

import api.post.server.create
import api.post.server.rebuild
import api.post.server.run
import api.post.server.stop
import api.post.server.delete
import api.post.server.owner
import api.post.server.hostname
import api.post.user.create
import api.post.user.delete

import api.post.user.assign_memory
import api.post.user.reset_password
import api.post.server.memory
import api.velocity

USER = None
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

def ApiPostServerStop(cmd):
    args = cmd[len("server stop "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            server_name = input("Enter server name to stop: ").strip()
            if server_name == '':
                print("Server name cannot be empty.")
                continue
            args = [server_name]
    else:
        server_name = args[0]
    response = api.post.server.stop.stop_server(server_name)
    return print(f"Server stop response: {response}")

def ApiPostServerDelete(cmd):
    args = cmd[len("server delete "):].strip().split()
    if len(args) < 1:
        server_name = input("Enter server name to delete: ").strip()
        if server_name == '':
            print("Server name cannot be empty.")
            return
    else:
        server_name = args[0]
    
    remove_data = False
    confirm = input(f"Delete server '{server_name}'? Also remove data? (y/n): ").strip().lower()
    if confirm == 'y':
        remove_data = True
    
    response = api.post.server.delete.delete_server(server_name, remove_data=remove_data)
    return print(f"Server delete response: {response}")

def ApiPostServerHostname(cmd):
    args = cmd[len("server hostname "):].strip().split()
    if len(args) < 2:
        print("Usage: server hostname <server_name> <new_hostname>")
        print("  Use 'none' to clear the hostname.")
        return
    
    server_name = args[0]
    new_hostname = args[1]
    
    if new_hostname.lower() == 'none':
        new_hostname = ""
        
    response = api.post.server.hostname.update_hostname(server_name, new_hostname)
    return print(response)

def ApiPostServerMemory(cmd):
    args = cmd[len("server memory "):].strip().split()
    if len(args) < 2:
        print("Usage: server memory <server_name> <memory_mb>")
        return
    
    server_name = args[0]
    try:
        memory_mb = int(args[1])
    except ValueError:
        print("Memory must be an integer.")
        return
        
    import api.post.server.memory
    response = api.post.server.memory.assign_memory(server_name, memory_mb, USER)
    return print(response)

def ApiGetServerStatus(cmd):
    args = cmd[len("server status "):].strip().split()
    if len(args) != 1:
        while len(args) != 1:
            server_name = input("Enter server name for status: ").strip()
            if server_name == '':
                print("Server name cannot be empty.")
                continue
            args = [server_name]
    else:
        server_name = args[0]
    status = api.post.server.run.get_server_status(server_name)
    if isinstance(status, dict):
        print(f"  Name:      {status['name']}")
        print(f"  Container: {status['container']}")
        print(f"  Status:    {status['status']}")
        print(f"  Port:      {status['port']}")
        print(f"  Hostname:  {status['hostname']}")
    else:
        print(status)

def ApiVelocityStart():
    api.velocity.download_velocity()
    api.velocity.start_velocity()

def ApiVelocityStop():
    api.velocity.stop_velocity()

def ApiVelocityReload():
    api.velocity.reload_velocity_config()

def ApiVelocityStatus():
    import os
    pid_file = api.velocity.VELOCITY_PID_FILE
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 0)
            print(f"Velocity is running (PID {pid}).")
        except ProcessLookupError:
            print("Velocity PID file exists but process is not running.")
    else:
        print("Velocity is not running.")

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

def ApiPostUserAssignMemory(cmd):
    args = cmd[len("user assign "):].strip().split()
    if len(args) != 2:
        print("Usage: user assign <username> <limit_mb>")
        return
    username = args[0]
    try:
        limit_mb = int(args[1])
    except ValueError:
        print("Memory must be an integer.")
        return
    response = api.post.user.assign_memory.assign_memory(username, limit_mb)
    print(response)

def ApiPostUserResetPassword(cmd):
    args = cmd[len("user reset-password "):].strip().split()
    if len(args) != 2:
        print("Usage: user reset-password <username> <new_password>")
        return
    username = args[0]
    new_password = args[1]
    response = api.post.user.reset_password.reset_password(username, new_password)
    print(response)

def ApiUserLogin(cmd):
    global USER
    args = cmd[len("login "):].strip().split()
    if len(args) == 0:
        username = input("Username: ").strip()
        import getpass
        password = getpass.getpass("Password: ").strip()
    elif len(args) == 2:
        username = args[0]
        password = args[1]
    else:
        print("Usage: login [username] [password]")
        return
        
    if getattr(api.db, 'verify_user_password')(username, password):
        USER = username
        print(f"Successfully logged in as {username}.")
    else:
        print("Invalid username or password.")

while True:
    try:
        if USER is None:
            cmd = input("Login required. Type 'login' or 'exit': ")
            if cmd.lower() == 'exit':
                break
            elif cmd.startswith('login'):
                ApiUserLogin(cmd)
            continue
            
        cmd = input(USER + ">> ")
        if cmd.lower() == 'exit':
            print("Exiting the program.")
            break

        elif cmd.strip() == '':
            continue

        elif cmd == "help":
            print("Available commands:")
            print("  helloworld               - Get a hello world message")
            print("  server create <name> <type> <version> - Create a new server")
            print("  server rebuild <name>    - Rebuild a server and update info")
            print("  server run <name>        - Start a server in Docker container")
            print("  server stop <name>       - Stop a server container")
            print("  server delete <name>     - Delete a server and its container")
            print("  server hostname <n> <h>  - Update hostname for a server")
            print("  server memory <n> <mb>   - Assign memory to a server")
            print("  server status <name>     - Check server container status")
            print("  server console <name>    - Open RCON console")
            print("  server owner <n> <u>     - Transfer server ownership")
            print("  user add <name>          - Create a new user (admin only)")
            print("  user remove <name>       - Delete a user (admin only)")
            print("  user assign <name> <mb>  - Assign memory limit to a user (admin only)")
            print("  user reset-password <n> <p> - Reset user password (admin only)")
            print("  user list                - List all users")
            print("  velocity start           - Download and start Velocity proxy")
            print("  velocity stop            - Stop Velocity proxy")
            print("  velocity reload          - Reload Velocity config from DB")
            print("  velocity status          - Check Velocity process status")
            print("  logout                   - Logout current user")
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
                    elif cmd_server.startswith("stop"):
                        ApiPostServerStop("server " + cmd_server)
                    elif cmd_server.startswith("delete"):
                        ApiPostServerDelete("server " + cmd_server)
                    elif cmd_server.startswith("hostname"):
                        ApiPostServerHostname("server " + cmd_server)
                    elif cmd_server.startswith("memory"):
                        ApiPostServerMemory("server " + cmd_server)
                    elif cmd_server.startswith("status"):
                        ApiGetServerStatus("server " + cmd_server)
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

            elif cmd.startswith("server stop"):
                ApiPostServerStop(cmd)

            elif cmd.startswith("server delete"):
                ApiPostServerDelete(cmd)

            elif cmd.startswith("server hostname"):
                ApiPostServerHostname(cmd)
                
            elif cmd.startswith("server memory"):
                ApiPostServerMemory(cmd)

            elif cmd.startswith("server status"):
                ApiGetServerStatus(cmd)

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

            elif cmd.startswith("user create") or cmd.startswith("user add"):
                ApiPostUserCreate(cmd.replace("user add", "user create"))

            elif cmd.startswith("user delete") or cmd.startswith("user remove"):
                ApiPostUserDelete(cmd.replace("user remove", "user delete"))

            elif cmd.startswith("user list"):
                ApiGetUserList()
                
            elif cmd.startswith("user assign"):
                ApiPostUserAssignMemory(cmd)
                
            elif cmd.startswith("user reset-password"):
                ApiPostUserResetPassword(cmd)

            else:
                print("Invalid user command. Type 'help' for a list of commands.")

        elif cmd.lower() == "logout":
            USER = None
            print("Logged out successfully.")

        elif cmd.startswith("velocity"):
            if cmd == "velocity" or cmd == "velocity help":
                print("Velocity commands:")
                print("  velocity start   - Download and start Velocity proxy")
                print("  velocity stop    - Stop Velocity proxy")
                print("  velocity reload  - Reload Velocity config from DB")
                print("  velocity status  - Check Velocity process status")
            elif cmd == "velocity start":
                ApiVelocityStart()
            elif cmd == "velocity stop":
                ApiVelocityStop()
            elif cmd == "velocity reload":
                ApiVelocityReload()
            elif cmd == "velocity status":
                ApiVelocityStatus()
            else:
                print("Invalid velocity command. Type 'velocity help'.")

        else:
            print("Invalid command. Please try again.")
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting.")
        break
    except Exception as e:
        print(f"An error occurred: {e}")
        break