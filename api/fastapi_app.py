import os
import asyncio
import threading
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Depends, HTTPException, Cookie, Response, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

# Import existing backend modules
import api.db
import api.auth
import api.infrared
import api.post.server.create
import api.get.forge
import api.get.neoforge
import api.post.server.run
import api.post.server.stop
import api.post.server.hostname
import api.post.server.memory
import api.post.server.delete
import api.post.user.assign_memory
import api.post.user.reset_password
import api.post.user.create
import api.post.user.delete

# Define the absolute directory to serve frontend files from
frontend_dir = Path(__file__).parent.resolve() / "get" / "ui"

# --- Socket.IO Server Setup ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Global variable to store running asyncio loop for thread-safe emissions from sync threads
loop = None
last_known_statuses = {}

# Active background loop for container status polling
async def status_polling_loop():
    while True:
        try:
            servers = api.db.get_all_servers()
            changed = False
            for srv in servers:
                name = srv["name"]
                status_info = api.post.server.run.get_server_status(name)
                status = status_info.get("status", "UNKNOWN") if isinstance(status_info, dict) else "UNKNOWN"
                if last_known_statuses.get(name) != status:
                    last_known_statuses[name] = status
                    changed = True
            
            # Detect if a server was deleted
            srv_names = {s["name"] for s in servers}
            deleted_names = [name for name in list(last_known_statuses.keys()) if name not in srv_names]
            for name in deleted_names:
                del last_known_statuses[name]
                changed = True

            if changed:
                await sio.emit("servers_updated", {})
        except Exception as e:
            print(f"[Status Polling Loop Error] {e}")
        await asyncio.sleep(3)

# Thread-safe callback hook to push container build/download logs in real time
def socketio_log_callback(server_name, line):
    if loop and sio:
        asyncio.run_coroutine_threadsafe(
            sio.emit("logs_append", {"name": server_name, "line": line}, room=f"logs:{server_name}"),
            loop
        )

# Register the callback hook early with the server creation and mods modules
import api.post.server.mods
api.post.server.create.register_log_callback(socketio_log_callback)
api.post.server.mods.register_log_callback(socketio_log_callback)

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    
    # Initialize the database on startup
    api.db.init_db()
    
    # Generate Infrared config files
    try:
        api.infrared.generate_infrared_config()
        api.infrared.generate_proxy_files()
        print("[Startup] Infrared configuration generated.")
    except Exception as e:
        print(f"[Startup] Warning: Could not generate Infrared config: {e}")
        
    # Start the active status polling task in the background
    polling_task = asyncio.create_task(status_polling_loop())
    
    yield
    
    # Clean up polling task on shutdown
    polling_task.cancel()

# Initialize FastAPI App (underlying router app)
fastapi_app = FastAPI(title="Minecraft Server Manager", lifespan=lifespan)

# --- Exception Handlers for Frontend Compatibility ---
@fastapi_app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

@fastapi_app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if errors:
        msg = f"Validation failed: {errors[0]['loc'][-1]} - {errors[0]['msg']}"
    else:
        msg = "Invalid request payload"
    return JSONResponse(
        status_code=400,
        content={"error": msg}
    )

@fastapi_app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )

# --- Authentication & Authorization Dependencies ---
def get_current_user(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = api.auth.get_session_user(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user

def get_admin_user(current_user: str = Depends(get_current_user)):
    if current_user != 'admin':
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user

def check_server_access(server_name: str, user: str) -> bool:
    if user == 'admin':
        return True
    info = api.db.get_server_info(server_name)
    if info and info['owner'] == user:
        return True
    return False

# --- Pydantic Models for POST requests ---
class LoginRequest(BaseModel):
    username: str
    password: str

class CreateServerRequest(BaseModel):
    name: str
    type: str = "spigot"
    version: str
    owner: str = "admin"
    memory_mb: int = 1024

class ServerNameRequest(BaseModel):
    name: str

class DeleteServerRequest(BaseModel):
    name: str
    remove_data: bool = False

class UpdateHostnameRequest(BaseModel):
    name: str
    hostname: str

class UpdateMemoryRequest(BaseModel):
    name: str
    memory_mb: int

class UserRequest(BaseModel):
    username: str

class AssignMemoryRequest(BaseModel):
    username: str
    limit_mb: int

class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

class CommandRequest(BaseModel):
    name: str
    command: str

# ============================================================================
# Auth Endpoints
# ============================================================================
@fastapi_app.post("/api/auth/login")
async def login(data: LoginRequest, response: Response):
    username = data.username.strip()
    password = data.password.strip()
    if api.db.verify_user_password(username, password):
        token = api.auth.create_session(username)
        response.set_cookie(key="session_id", value=token, path="/", httponly=True)
        return {"message": "Success", "username": username}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@fastapi_app.post("/api/auth/logout")
async def logout(response: Response, session_id: Optional[str] = Cookie(default=None)):
    if session_id:
        api.auth.delete_session(session_id)
    response.delete_cookie(key="session_id", path="/")
    return {"message": "Logged out"}

@fastapi_app.get("/api/auth/me")
async def auth_me(current_user: str = Depends(get_current_user)):
    user_info = api.db.get_user_info(current_user)
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    return user_info

# ============================================================================
# User Endpoints (Admin Only)
# ============================================================================
@fastapi_app.get("/api/users")
async def get_users(admin_user: str = Depends(get_admin_user)):
    return {"users": [api.db.get_user_info(u) for u in api.db.get_users()]}

@fastapi_app.post("/api/user/add")
async def user_add(data: UserRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.create.create_user(username)
    return {"message": res}

@fastapi_app.post("/api/user/remove")
async def user_remove(data: UserRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.delete.delete_user(username)
    return {"message": res}

@fastapi_app.post("/api/user/assign")
async def user_assign(data: AssignMemoryRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.assign_memory.assign_memory(username, data.limit_mb)
    return {"message": res}

@fastapi_app.post("/api/user/reset")
async def user_reset(data: ResetPasswordRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    new_password = data.new_password.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.reset_password.reset_password(username, new_password)
    return {"message": res}

# ============================================================================
# Server Endpoints
# ============================================================================
@fastapi_app.get("/api/servers")
async def get_servers(current_user: str = Depends(get_current_user)):
    servers = api.db.get_all_servers()
    
    # Filter servers if not admin
    if current_user != 'admin':
        servers = [srv for srv in servers if srv['owner'] == current_user]
        
    for srv in servers:
        status = api.post.server.run.get_server_status(srv["name"])
        if isinstance(status, dict):
            srv["status"] = status.get("status", "UNKNOWN")
        else:
            srv["status"] = "UNKNOWN"
        srv["eula_agreed"] = api.post.server.run.is_eula_agreed(srv["name"])
    return {"servers": servers}

@fastapi_app.get("/api/server/{name}")
async def get_server(name: str, current_user: str = Depends(get_current_user)):
    server = api.db.get_server_info(name)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
        
    if current_user != 'admin' and server['owner'] != current_user:
        raise HTTPException(status_code=403, detail="Access denied")
        
    status = api.post.server.run.get_server_status(name)
    if isinstance(status, dict):
        server["status"] = status.get("status", "UNKNOWN")
    else:
        server["status"] = "UNKNOWN"
    server["eula_agreed"] = api.post.server.run.is_eula_agreed(name)
    return server

@fastapi_app.get("/api/server/{name}/creation-logs")
async def get_server_creation_logs(name: str, current_user: str = Depends(get_current_user)):
    server = api.db.get_server_info(name)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
        
    if current_user != 'admin' and server['owner'] != current_user:
        raise HTTPException(status_code=403, detail="Access denied")
        
    log_content = ""
    log_paths = [
        f"data/servers/{name}/creation.log",
        f"data/servers/{name}/buildtools.log"
    ]
    for p in log_paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    log_content = f.read()
                break
            except Exception as e:
                log_content = f"Error reading log file: {e}"
    else:
        log_content = "No creation logs found yet. Please wait..."
        
    return {"logs": log_content}

@fastapi_app.post("/api/server/create", status_code=202)
async def create_server(data: CreateServerRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    server_type = data.type.strip()
    version = data.version.strip()
    owner = data.owner.strip()

    if not name or not version:
        raise HTTPException(status_code=400, detail="name and version are required")

    # Only admin can create servers for other owners
    if current_user != 'admin' and owner != current_user:
        raise HTTPException(status_code=403, detail="Access denied: Cannot create server for another user")

    # Force owner to current user if not admin
    if current_user != 'admin':
        owner = current_user

    memory_mb = data.memory_mb
    if memory_mb < 512:
        raise HTTPException(status_code=400, detail="memory_mb must be at least 512")

    # Validate against user memory limit (admin bypasses)
    if current_user != 'admin':
        user_info = api.db.get_user_info(owner)
        if user_info:
            memory_limit = user_info['memory_limit']
            servers = api.db.get_all_servers()
            used = sum(srv.get('memory_mb', 1024) for srv in servers if srv['owner'] == owner)
            if (used + memory_mb) > memory_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot allocate {memory_mb} MB. Limit: {memory_limit} MB, already used: {used} MB."
                )

    threading.Thread(
        target=api.post.server.create.create_server,
        args=(name, server_type, version),
        kwargs={"owner": owner, "memory_mb": memory_mb},
        daemon=True
    ).start()
    
    # Broadcast status change instantly to clients
    await sio.emit("servers_updated", {})
    
    return {"message": f"Creation of '{name}' started in background."}

@fastapi_app.get("/api/forge/versions")
async def get_forge_versions_endpoint(mc_version: str, current_user: str = Depends(get_current_user)):
    mc_version = mc_version.strip()
    if not mc_version:
        raise HTTPException(status_code=400, detail="mc_version is required")
    try:
        data = api.get.forge.get_forge_versions(mc_version)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Forge versions: {str(e)}")

@fastapi_app.get("/api/neoforge/versions")
async def get_neoforge_versions_endpoint(mc_version: str, current_user: str = Depends(get_current_user)):
    mc_version = mc_version.strip()
    if not mc_version:
        raise HTTPException(status_code=400, detail="mc_version is required")
    try:
        data = api.get.neoforge.get_neoforge_versions(mc_version)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch NeoForge versions: {str(e)}")

@fastapi_app.post("/api/server/install")
async def install_server(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
        
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    threading.Thread(
        target=api.post.server.create.install_forge,
        args=(name,),
        daemon=True
    ).start()
    
    await sio.emit("servers_updated", {})
    return {"message": f"Installation of Forge on '{name}' started in background."}

@fastapi_app.post("/api/server/{name}/upload-mod")
async def upload_mod(name: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not file.filename.endswith(".jar"):
        raise HTTPException(status_code=400, detail="Only .jar files are allowed")
        
    mods_dir = os.path.abspath(f"data/servers/{name}/mods")
    os.makedirs(mods_dir, exist_ok=True)
    
    file_path = os.path.join(mods_dir, file.filename)
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"message": f"Successfully uploaded {file.filename} to mods folder."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save mod: {str(e)}")

@fastapi_app.post("/api/server/{name}/upload-modlist")
async def upload_modlist(name: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not file.filename.endswith(".html") and not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only CurseForge exported .html modlists or manifest.json files are allowed")
        
    try:
        content_bytes = await file.read()
        html_content = content_bytes.decode("utf-8", errors="replace")
        
        # Clear/initialize creation.log so the logs modal shows fresh downloading output!
        log_path = os.path.join("data", "servers", name, "creation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Initiated mod list download from CurseForge Modlist HTML: {file.filename}\n")
            
        # Start the mod downloader inside a separate container
        api.post.server.mods.start_mod_download_container(name, html_content)
        
        # Broadcast status updates
        await sio.emit("servers_updated", {})
        
        return {"message": "CurseForge mod list parsed. Downloading mods in background..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse mod list: {str(e)}")

@fastapi_app.post("/api/server/agree-eula")
async def agree_eula(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = api.post.server.run.agree_to_eula(name)
    await sio.emit("servers_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/run")
async def run_server(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await asyncio.to_thread(api.post.server.run.run_server, name)
    await sio.emit("servers_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/stop")
async def stop_server(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await asyncio.to_thread(api.post.server.stop.stop_server, name) 
    await sio.emit("servers_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/delete")
async def delete_server(data: DeleteServerRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await asyncio.to_thread(api.post.server.delete.delete_server, name, data.remove_data)
    # Clean up stored console commands for this server
    try:
        api.db.delete_console_commands(name)
    except Exception as e:
        print(f"[DB] Warning: could not delete console commands for '{name}': {e}")
    await sio.emit("servers_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/cancel-mod-download")
async def cancel_mod_download(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
        
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    import docker
    client = docker.from_env()
    container_name = f"mc-mod-downloader-{name}"
    try:
        container = client.containers.get(container_name)
        container.stop(timeout=2)
        container.remove()
        await sio.emit("servers_updated", {})
        return {"message": "Mod download cancelled and container stopped."}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="No active mod downloader found for this server.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel mod download: {str(e)}")

@fastapi_app.post("/api/server/hostname")
async def server_hostname(data: UpdateHostnameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    hostname = data.hostname.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = api.post.server.hostname.update_hostname(name, hostname)
    await sio.emit("servers_updated", {})
    await sio.emit("proxy_routes_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/memory")
async def server_memory(data: UpdateMemoryRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    memory_mb = data.memory_mb
    
    if not name or memory_mb is None:
        raise HTTPException(status_code=400, detail="name and memory_mb are required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    result = api.post.server.memory.assign_memory(name, memory_mb, current_user)
    if "Failed" in result or "exceeded" in result or "not found" in result:
        raise HTTPException(status_code=400, detail=result)
    else:
        await sio.emit("servers_updated", {})
        return {"message": result}

@fastapi_app.post("/api/server/command")
async def execute_command(data: CommandRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    command = data.command.strip()
    
    if not name or not command:
        raise HTTPException(status_code=400, detail="name and command are required")
        
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_info = api.db.get_server_info(name)
    if not server_info:
        raise HTTPException(status_code=404, detail="Server not found in DB")
        
    container_name = server_info.get("container_name") or f"mc-{name}"
    
    try:
        # 1. Persist the command to PostgreSQL so it survives console re-opens
        from datetime import datetime, timezone
        try:
            api.db.log_console_command(name, current_user, command)
        except Exception as db_err:
            print(f"[Console DB Write Error] {db_err}")

        # 2. Write the CMD line directly into latest.log. The JVM also writes
        #    to this file via log4j with O_APPEND, so a small (<PIPE_BUF) append
        #    from us interleaves atomically at line boundaries. The streaming
        #    worker polls the file and pushes a full snapshot to clients on any
        #    change — no per-line socket emit, no client-side appending.
        ts = datetime.now().strftime("%H:%M:%S")
        cmd_line = f"[{ts}] [Console/CMD]: {command}\n"
        log_path = f"data/servers/{name}/logs/latest.log"
        if os.path.exists(log_path):
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(cmd_line)
            except Exception as write_err:
                print(f"[Console] Could not append CMD line to {log_path}: {write_err}")

        # Push an immediate snapshot so the CMD line shows without waiting
        # for the polling worker's next tick.
        try:
            snapshot = read_latest_log_tail(name)
            await sio.emit(
                "console_init",
                {"name": name, "logs": snapshot},
                room=f"console:{name}",
            )
        except Exception as snap_err:
            print(f"[Console] Snapshot emit error: {snap_err}")

        # 3. Send the command to container stdin — same path for every command,
        #    including `stop`. Sending it via stdin lets Minecraft run its
        #    normal shutdown sequence and emit its usual log lines.
        import docker
        client = docker.from_env()
        container = client.containers.get(container_name)

        sock = container.attach_socket(params={'stdin': 1, 'stream': 1})
        payload = (command + "\n").encode("utf-8")

        if hasattr(sock, '_sock'):
            sock._sock.sendall(payload)
        elif hasattr(sock, 'send'):
            sock.send(payload)
        else:
            sock.write(payload)

        sock.close()

        # 4. For `stop`: once Minecraft has finished saving (sentinel line),
        #    call container.stop() so Docker marks the exit as user-initiated
        #    and the `unless-stopped` restart policy doesn't bring it back up.
        if command.strip().lower() == "stop":
            def _watch_and_stop(container_obj, srv_name):
                import time as _time
                sentinel = "ThreadedAnvilChunkStorage: All dimensions are saved"
                watch_path = f"data/servers/{srv_name}/logs/latest.log"
                file_pos = os.path.getsize(watch_path) if os.path.exists(watch_path) else 0
                deadline = _time.time() + 60
                seen = False
                while _time.time() < deadline and not seen:
                    try:
                        if os.path.exists(watch_path):
                            with open(watch_path, "r", encoding="utf-8", errors="ignore") as wf:
                                wf.seek(file_pos)
                                for ln in wf:
                                    file_pos += len(ln.encode("utf-8"))
                                    if sentinel in ln:
                                        seen = True
                                        break
                    except Exception as read_err:
                        print(f"[Stop Watch] read error for '{srv_name}': {read_err}")
                    if not seen:
                        _time.sleep(0.3)

                try:
                    container_obj.reload()
                    if container_obj.status == "running":
                        container_obj.stop(timeout=30)
                except Exception as stop_err:
                    print(f"[Stop Watch] stop error for '{srv_name}': {stop_err}")

                if loop:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            sio.emit("servers_updated", {}), loop,
                        )
                    except Exception as emit_err:
                        print(f"[Stop Watch] emit error for '{srv_name}': {emit_err}")

            threading.Thread(
                target=_watch_and_stop,
                args=(container, name),
                daemon=True,
            ).start()

        return {"response": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute command on stdin: {str(e)}")

# ============================================================================
# Proxy (Infrared) Control & Status (Admin Only)
# ============================================================================
@fastapi_app.get("/api/proxy/status")
async def get_proxy_status(current_user: str = Depends(get_current_user)):
    import docker as docker_mod
    try:
        client = docker_mod.from_env()
        container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
        running = container.status == "running"
        return {"running": running, "container": container.status}
    except docker_mod.errors.NotFound:
        return {"running": False, "container": "not found"}
    except Exception as e:
        return {"running": False, "container": str(e)}

@fastapi_app.get("/api/proxy/routes")
async def get_proxy_routes(admin_user: str = Depends(get_admin_user)):
    proxies_dir = "data/infrared/proxies"
    routes = []
    if os.path.exists(proxies_dir):
        for fname in os.listdir(proxies_dir):
            if fname.endswith(".yml"):
                path = os.path.join(proxies_dir, fname)
                try:
                    with open(path, "r") as f:
                        content = f.read()
                    domain = "unknown"
                    address = "unknown"
                    for line in content.splitlines():
                        line_strip = line.strip()
                        if line_strip.startswith("-"):
                            val = line_strip[1:].strip().strip('"').strip("'")
                            if ":" in val:
                                address = val
                            else:
                                domain = val
                    routes.append({
                        "file": fname,
                        "domain": domain,
                        "address": address,
                        "content": content
                    })
                except Exception as e:
                    print(f"Error parsing proxy {fname}: {e}")
    return {"routes": routes}

@fastapi_app.post("/api/proxy/start")
async def proxy_start(admin_user: str = Depends(get_admin_user)):
    api.infrared.reload_proxy_config()
    import docker as docker_mod
    try:
        client = docker_mod.from_env()
        container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
        if container.status != "running":
            container.start()
        await sio.emit("proxy_routes_updated", {})
        return {"message": "Infrared container started; config reloaded."}
    except docker_mod.errors.NotFound:
        return {"message": "Infrared config written; container not found (start via docker-compose)."}

@fastapi_app.post("/api/proxy/stop")
async def proxy_stop(admin_user: str = Depends(get_admin_user)):
    import docker as docker_mod
    try:
        client = docker_mod.from_env()
        container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
        container.stop(timeout=10)
        await sio.emit("proxy_routes_updated", {})
        return {"message": "Infrared container stopped."}
    except docker_mod.errors.NotFound:
        return {"message": "Infrared container not found."}

@fastapi_app.post("/api/proxy/reload")
async def proxy_reload(admin_user: str = Depends(get_admin_user)):
    api.infrared.reload_proxy_config()
    await sio.emit("proxy_routes_updated", {})
    return {"message": "Infrared config reloaded"}

# ============================================================================
# Socket.IO Event Handlers
# ============================================================================

# Track active consoles: server_name -> {"sids": set()}
active_consoles = {}

def read_latest_log_tail(server_name, max_lines=400):
    """
    Build the initial console snapshot shown when a client opens the console.

    Merges the tail of ``latest.log`` with command history from PostgreSQL,
    sorted chronologically.  Both sources use ``HH:MM:SS`` timestamps.

    Within the same second, **commands come first** (priority 0) so that
    ``[20:15:52] [Console/CMD]: > gamerule keepInventory`` appears before
    ``[20:15:52] [Server thread/INFO]: Incorrect argument …``.
    """
    import re
    from collections import deque

    log_path = f"data/servers/{server_name}/logs/latest.log"

    # --- 1. Read the tail of latest.log  (priority=1 — appears after commands) ---
    # Each entry: (time_str, priority, raw_line)
    entries = []
    existing_lines = set()
    first_log_ts = None
    ts_re = re.compile(r'^\[(?:[^\]]*\s)?(\d{2}:\d{2}:\d{2})(?:\.\d+)?\]')
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                tail = deque(f, maxlen=max_lines)
            for raw in tail:
                existing_lines.add(raw)
                m = ts_re.match(raw)
                if m:
                    ts_val = m.group(1)
                    if first_log_ts is None:
                        first_log_ts = ts_val
                    entries.append((ts_val, 1, raw))
                else:
                    entries.append(("00:00:00", 1, raw))
        except Exception as e:
            return f"Error reading log file: {e}"

    # --- 2. Fetch DB commands  (priority=0 — appears before server response) ---
    # Only show DB commands once the server has written its first timestamped
    # line — otherwise the console would display the entire historical command
    # history while latest.log is still empty (e.g. during startup or before a
    # fresh log rotation).  Also skip commands already present in latest.log
    # (injected on previous stop) and any whose HH:MM:SS predates the first
    # log line (previous session, since rotated out).
    if first_log_ts is not None:
        try:
            cmds = api.db.get_console_commands(server_name, limit=max_lines)
            for c in cmds:
                local_dt = c["sent_at"].astimezone()
                ts = local_dt.strftime("%H:%M:%S")
                if ts < first_log_ts:
                    continue
                line = f"[{ts}] [Console/CMD]: {c['command']}\n"
                if line in existing_lines:
                    continue
                entries.append((ts, 0, line))
        except Exception as e:
            print(f"[Console] Warning: could not load DB commands: {e}")

    if not entries:
        return "No console logs found yet. Please start the server..."

    # --- 3. Sort by (time_str, priority) — commands (0) sort before log (1) ---
    entries.sort(key=lambda x: (x[0], x[1]))
    return "".join(line for _, _, line in entries)

def latest_log_stream_worker(server_name, loop_obj):
    import os
    import time
    log_path = f"data/servers/{server_name}/logs/latest.log"
    print(f"[Console Stream] Starting stream for {server_name} from {log_path}")

    last_size = -1
    last_inode = -1
    last_existed = False

    while server_name in active_consoles:
        try:
            if os.path.exists(log_path):
                st = os.stat(log_path)
                size = st.st_size
                inode = st.st_ino
                if not last_existed or size != last_size or inode != last_inode:
                    last_size = size
                    last_inode = inode
                    last_existed = True
                    snapshot = read_latest_log_tail(server_name)
                    asyncio.run_coroutine_threadsafe(
                        sio.emit(
                            "console_init",
                            {"name": server_name, "logs": snapshot},
                            room=f"console:{server_name}",
                        ),
                        loop_obj,
                    )
            else:
                if last_existed or last_size != -1:
                    last_existed = False
                    last_size = -1
                    last_inode = -1
                    snapshot = read_latest_log_tail(server_name)
                    asyncio.run_coroutine_threadsafe(
                        sio.emit(
                            "console_init",
                            {"name": server_name, "logs": snapshot},
                            room=f"console:{server_name}",
                        ),
                        loop_obj,
                    )
            time.sleep(0.3)
        except Exception as e:
            print(f"[Console Stream Error] {e}")
            time.sleep(1)

@sio.event
async def connect(sid, environ):
    # Print connection details for debugging
    print(f"[WS Connect] Socket.IO client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[WS Disconnect] Socket.IO client disconnected: {sid}")
    # Clean up active consoles for this sid
    for server_name, info in list(active_consoles.items()):
        if sid in info["sids"]:
            info["sids"].remove(sid)
            if not info["sids"]:
                active_consoles.pop(server_name, None)

def _parse_server_name(data) -> str:
    if isinstance(data, dict):
        val = data.get("name")
        return str(val).strip() if val is not None else ""
    elif isinstance(data, str):
        return data.strip()
    return ""

@sio.on("join_console")
async def handle_join_console(sid, data):
    server_name = _parse_server_name(data)
    if not server_name:
        return
        
    room = f"console:{server_name}"
    await sio.enter_room(sid, room)
    print(f"[WS Console] Client {sid} joined console room for: {server_name}")
    
    # 1. Fetch initial logs from latest.log file only!
    initial_logs = read_latest_log_tail(server_name)
    await sio.emit("console_init", {"name": server_name, "logs": initial_logs}, room=sid)
    
    # 2. Check if a worker is already running for this server
    if server_name not in active_consoles:
        active_consoles[server_name] = {"sids": {sid}}
        import threading
        t = threading.Thread(
            target=latest_log_stream_worker,
            args=(server_name, asyncio.get_running_loop()),
            daemon=True
        )
        t.start()
    else:
        active_consoles[server_name]["sids"].add(sid)

@sio.on("leave_console")
async def handle_leave_console(sid, data):
    server_name = _parse_server_name(data)
    if not server_name:
        return
        
    room = f"console:{server_name}"
    await sio.leave_room(sid, room)
    print(f"[WS Console] Client {sid} left console room for: {server_name}")
    
    if server_name in active_consoles:
        info = active_consoles[server_name]
        if sid in info["sids"]:
            info["sids"].remove(sid)
            if not info["sids"]:
                active_consoles.pop(server_name, None)


@sio.on("join_creation_logs")
async def handle_join_creation_logs(sid, data):
    server_name = _parse_server_name(data)
    if not server_name:
        return
        
    room = f"logs:{server_name}"
    await sio.enter_room(sid, room)
    print(f"[WS Logs] Client {sid} joined creation logs room for: {server_name}")
    
    # Read the current contents of the logs to initialize the client view
    log_content = ""
    log_paths = [
        f"data/servers/{server_name}/creation.log",
        f"data/servers/{server_name}/buildtools.log"
    ]
    for p in log_paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    log_content = f.read()
                break
            except Exception as e:
                log_content = f"Error reading log file: {e}"
    else:
        log_content = "No creation logs found yet. Please wait..."
        
    await sio.emit("logs_init", {"name": server_name, "logs": log_content}, room=sid)

@sio.on("leave_creation_logs")
async def handle_leave_creation_logs(sid, data):
    server_name = _parse_server_name(data)
    if not server_name:
        return
        
    room = f"logs:{server_name}"
    await sio.leave_room(sid, room)
    print(f"[WS Logs] Client {sid} left creation logs room for: {server_name}")

# ============================================================================
# Static Files & View Routing
# ============================================================================
@fastapi_app.get("/")
async def serve_index():
    return FileResponse(frontend_dir / "index.html")

@fastapi_app.get("/login.html")
async def serve_login():
    return FileResponse(frontend_dir / "login.html")

@fastapi_app.get("/infrared")
async def serve_infrared(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return RedirectResponse(url="/login.html", status_code=302)
    user = api.auth.get_session_user(session_id)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    if user != 'admin':
        raise HTTPException(status_code=403, detail="Access denied: Admin required")
    return FileResponse(frontend_dir / "infrared.html")

@fastapi_app.get("/api.js")
async def serve_api_js():
    path = frontend_dir / "api.js"
    if path.exists():
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Not Found")

# Mount Static subfolders if they exist
if (frontend_dir / "css").exists():
    fastapi_app.mount("/css", StaticFiles(directory=str(frontend_dir / "css")), name="css")

if (frontend_dir / "js").exists():
    fastapi_app.mount("/js", StaticFiles(directory=str(frontend_dir / "js")), name="js")

if (frontend_dir / "assets").exists():
    fastapi_app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")

# Wrap the FastAPI application under the Socket.IO ASGI wrapper
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
