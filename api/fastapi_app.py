import os
import asyncio
import threading
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Depends, HTTPException, Cookie, Response, Request, UploadFile, File, Form
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
import api.voicechat
import api.https

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
    
    # Check HTTPS status and verify Nginx is running
    try:
        threading.Thread(target=api.https.check_https_on_startup, daemon=True).start()
    except Exception as e:
        print(f"[Startup Warning] Could not verify HTTPS status: {e}")
    
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

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class HttpsSettingsRequest(BaseModel):
    enabled: bool
    domain: str = ""

class CommandRequest(BaseModel):
    name: str
    command: str

class FirewallRuleCreate(BaseModel):
    protocol: str
    enabled: bool = True
    internal_port: int
    external_port: Optional[int] = None
    label: str = ""

class FirewallRuleUpdate(BaseModel):
    enabled: bool
    internal_port: int
    external_port: Optional[int] = None
    label: str = ""

class QuickSettingsRequest(BaseModel):
    server_port: int
    difficulty: Optional[str] = None
    enable_rcon: Optional[bool] = None
    gamemode: Optional[str] = None
    hardcore: Optional[bool] = None
    level_name: Optional[str] = None
    level_seed: Optional[str] = None
    level_type: Optional[str] = None
    max_players: Optional[int] = None
    motd: Optional[str] = None
    online_mode: Optional[bool] = None
    rcon_password: Optional[str] = None
    rcon_port: Optional[int] = None
    simulation_distance: Optional[int] = None
    spawn_protection: Optional[int] = None
    view_distance: Optional[int] = None
    white_list: Optional[bool] = None
    voicechat: Optional[dict] = None

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

@fastapi_app.post("/api/user/change-password")
async def user_change_password(data: ChangePasswordRequest, current_user: str = Depends(get_current_user)):
    current_password = data.current_password
    new_password = data.new_password.strip()
    
    if not new_password:
        raise HTTPException(status_code=400, detail="New password cannot be empty")
        
    if not api.db.verify_user_password(current_user, current_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    success = api.db.set_user_password(current_user, new_password)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Password changed successfully"}

# ============================================================================
# System Endpoints (Admin Only)
# ============================================================================
@fastapi_app.get("/api/system/https")
async def get_system_https(admin_user: str = Depends(get_admin_user)):
    return api.https.get_https_status()

@fastapi_app.post("/api/system/https")
async def set_system_https(data: HttpsSettingsRequest, admin_user: str = Depends(get_admin_user)):
    if data.enabled:
        domain = data.domain.strip()
        if not domain:
            raise HTTPException(status_code=400, detail="Domain name is required to enable HTTPS")
        api.https.enable_https_async(domain)
        return {"message": "HTTPS enabling workflow started in background."}
    else:
        api.https.disable_https()
        return {"message": "HTTPS reverse proxy disabled successfully."}

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
        srv["port"] = api.db.get_server_port_from_properties(srv["name"])
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
    server["port"] = api.db.get_server_port_from_properties(name)
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

    # Force owner to current user if not admin
    if current_user != 'admin':
        owner = current_user

    # Only admin can create servers for other owners
    if current_user != 'admin' and owner != current_user:
        raise HTTPException(status_code=403, detail="Access denied: Cannot create server for another user")

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

# ============================================================================
# File Explorer Endpoints
# ============================================================================
@fastapi_app.get("/api/server/{name}/files")
async def list_server_files(name: str, path: str = "", current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_dir = os.path.abspath(f"data/servers/{name}")
    if not os.path.exists(server_dir):
        raise HTTPException(status_code=404, detail="Server folder not found")
        
    # Security check: resolve target path and verify it lies within server_dir
    target_dir = os.path.abspath(os.path.join(server_dir, path.strip("/")))
    if not target_dir.startswith(server_dir):
        raise HTTPException(status_code=400, detail="Invalid path traversal attempt")
        
    if not os.path.exists(target_dir):
        return {"files": [], "current_path": path}
        
    files_list = []
    try:
        for item in os.listdir(target_dir):
            # Ignore hidden files
            if item.startswith('.'):
                continue
            item_path = os.path.join(target_dir, item)
            rel_path = os.path.relpath(item_path, server_dir)
            is_dir = os.path.isdir(item_path)
            size = os.path.getsize(item_path) if not is_dir else 0
            files_list.append({
                "name": item,
                "path": rel_path,
                "is_dir": is_dir,
                "size": size
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {str(e)}")
        
    # Sort: directories first, then files, both alphabetically
    files_list.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return {"files": files_list, "current_path": path}

@fastapi_app.get("/api/server/{name}/file")
async def get_server_file(name: str, path: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_dir = os.path.abspath(f"data/servers/{name}")
    target_file = os.path.abspath(os.path.join(server_dir, path.strip("/")))
    if not target_file.startswith(server_dir) or not os.path.isfile(target_file):
        raise HTTPException(status_code=400, detail="Invalid or missing file path")
        
    try:
        # Check if gzip log file
        if path.endswith(".gz"):
            import gzip
            try:
                with gzip.open(target_file, "rt", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                return {"content": content, "is_binary": False, "path": path, "size": len(content)}
            except Exception as gz_err:
                raise HTTPException(status_code=500, detail=f"Failed to unzip log: {str(gz_err)}")
                
        # Check if text file by trying to read it
        with open(target_file, "rb") as f:
            raw_content = f.read()
        try:
            content = raw_content.decode("utf-8")
            is_binary = False
        except UnicodeDecodeError:
            content = "[Binary File - Preview and edits not supported in Web UI]"
            is_binary = True
            
        return {"content": content, "is_binary": is_binary, "path": path, "size": len(raw_content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

@fastapi_app.get("/api/server/{name}/logs")
async def list_server_logs(name: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_dir = os.path.abspath(f"data/servers/{name}")
    logs_dir = os.path.abspath(os.path.join(server_dir, "logs"))
    
    if not os.path.exists(logs_dir):
        return {"logs": []}
        
    logs_list = []
    try:
        for item in os.listdir(logs_dir):
            if item.startswith('.'):
                continue
            item_path = os.path.join(logs_dir, item)
            if os.path.isfile(item_path):
                rel_path = os.path.relpath(item_path, server_dir)
                size = os.path.getsize(item_path)
                mtime = os.path.getmtime(item_path)
                logs_list.append({
                    "name": item,
                    "path": rel_path,
                    "size": size,
                    "mtime": mtime
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list logs: {str(e)}")
        
    # Sort by modification time descending (newest first)
    logs_list.sort(key=lambda x: x["mtime"], reverse=True)
    return {"logs": logs_list}

@fastapi_app.post("/api/server/{name}/files")
async def upload_server_files(
    name: str,
    paths_json: str = Form(...),
    files: list[UploadFile] = File(...),
    current_user: str = Depends(get_current_user)
):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    import json
    try:
        paths = json.loads(paths_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid paths format. Must be JSON array.")
        
    if len(paths) != len(files):
        raise HTTPException(status_code=400, detail="Paths and files lists length mismatch")
        
    server_dir = os.path.abspath(f"data/servers/{name}")
    if not os.path.exists(server_dir):
        raise HTTPException(status_code=404, detail="Server folder not found")
        
    saved_count = 0
    try:
        for rel_path, file in zip(paths, files):
            target_file = os.path.abspath(os.path.join(server_dir, rel_path.strip("/")))
            if not target_file.startswith(server_dir):
                print(f"[Security Alert] File upload path '{rel_path}' escaped server root.")
                continue
                
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            
            content = await file.read()
            with open(target_file, "wb") as f:
                f.write(content)
            saved_count += 1
            
        # Post-upload properties files synchronization
        sync_server_props = False
        sync_vc_props = False
        for rel_path in paths:
            rel_path_lower = rel_path.lower()
            if "server.properties" in rel_path_lower:
                sync_server_props = True
            if "voicechat-server.properties" in rel_path_lower:
                sync_vc_props = True
                
        if sync_server_props:
            try:
                server_port = api.db.get_server_port_from_properties(name)
                rules = api.db.get_server_firewall_rules(name)
                primary_rule = None
                for r in rules:
                    if r["label"] == "Primary Game Port":
                        primary_rule = r
                        break
                if primary_rule and primary_rule["internal_port"] != server_port:
                    new_external = primary_rule["external_port"]
                    if primary_rule["external_port"] == primary_rule["internal_port"]:
                        new_external = server_port
                    api.db.update_firewall_rule(
                        primary_rule["id"],
                        primary_rule["enabled"],
                        server_port,
                        "Primary Game Port",
                        new_external
                    )
            except Exception as e:
                print(f"[Upload Properties Sync Error] {e}")
                
        if sync_vc_props:
            try:
                vc = api.voicechat.detect_voicechat(name)
                if vc["detected"] and vc["current_port"]:
                    vc_port = vc["current_port"]
                    rules = api.db.get_server_firewall_rules(name)
                    vc_rule = None
                    for r in rules:
                        if r["protocol"] == "UDP" and r["label"].strip().lower() == "simple voice chat":
                            vc_rule = r
                            break
                    if vc_rule and vc_rule["internal_port"] != vc_port:
                        api.db.update_firewall_rule(
                            vc_rule["id"],
                            vc_rule["enabled"],
                            vc_port,
                            "Simple Voice Chat"
                        )
            except Exception as e:
                print(f"[Upload Properties Sync Error] {e}")
            
        return {"message": f"Successfully uploaded/saved {saved_count} file(s)."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save files: {str(e)}")

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
        #    BUT if it's a stop command and the server is not fully booted yet,
        #    we bypass immediate execution to queue it and send it after booting.
        is_stop_cmd = command.strip().lower() == "stop"
        is_started = True
        if is_stop_cmd:
            is_started = api.post.server.stop.is_server_fully_started(name)

        if not is_stop_cmd or is_started:
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

        # 4. For `stop`: gracefully wait for it to exit, write saved log line,
        #    and stop the container so Docker marks it as stopped.
        if is_stop_cmd:
            if not is_started:
                # Spawn background thread to queue and send "stop" after it starts
                def _queue_and_send_stop(srv_name):
                    api.post.server.stop.stop_server(srv_name, send_cmd=True)
                    if loop:
                        try:
                            asyncio.run_coroutine_threadsafe(
                                sio.emit("servers_updated", {}), loop,
                            )
                        except Exception as emit_err:
                            print(f"[Stop Bg] emit error for '{srv_name}': {emit_err}")

                threading.Thread(
                    target=_queue_and_send_stop,
                    args=(name,),
                    daemon=True,
                ).start()
            else:
                # Already booted and sent stop, just monitor it
                def _watch_and_stop_bg(srv_name):
                    api.post.server.stop.stop_server(srv_name, send_cmd=False)
                    if loop:
                        try:
                            asyncio.run_coroutine_threadsafe(
                                sio.emit("servers_updated", {}), loop,
                            )
                        except Exception as emit_err:
                            print(f"[Stop Bg] emit error for '{srv_name}': {emit_err}")

                threading.Thread(
                    target=_watch_and_stop_bg,
                    args=(name,),
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
# Firewall Endpoints
# ============================================================================
@fastapi_app.get("/api/server/{name}/firewall")
async def get_server_firewall(name: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_port = api.db.get_server_port_from_properties(name)
    rules = api.db.get_server_firewall_rules(name)
    
    # Ensure primary port rule exists and matches server_port
    primary_rule = None
    for r in rules:
        if r["label"] == "Primary Game Port":
            primary_rule = r
            break
            
    if primary_rule:
        if primary_rule["internal_port"] != server_port:
            new_external = primary_rule["external_port"]
            if primary_rule["external_port"] == primary_rule["internal_port"]:
                new_external = server_port
            try:
                api.db.update_firewall_rule(
                    primary_rule["id"],
                    primary_rule["enabled"],
                    server_port,
                    "Primary Game Port",
                    new_external
                )
                rules = api.db.get_server_firewall_rules(name)
            except Exception as e:
                print(f"[Firewall Auto-Update Primary Rule Error] {e}")
    else:
        try:
            api.db.add_firewall_rule(name, "TCP", True, server_port, server_port, "Primary Game Port")
            rules = api.db.get_server_firewall_rules(name)
        except Exception as e:
            print(f"[Firewall Auto-Create Primary Rule Error] {e}")
            
    vc_info = api.voicechat.detect_voicechat(name)
    
    # Ensure voicechat rule matches properties port if it exists
    if vc_info["detected"] and vc_info["current_port"]:
        vc_port = vc_info["current_port"]
        vc_rule = None
        for r in rules:
            if r["protocol"] == "UDP" and r["label"].strip().lower() == "simple voice chat":
                vc_rule = r
                break
        if vc_rule and vc_rule["internal_port"] != vc_port:
            try:
                api.db.update_firewall_rule(
                    vc_rule["id"],
                    vc_rule["enabled"],
                    vc_port,
                    "Simple Voice Chat"
                )
                rules = api.db.get_server_firewall_rules(name)
            except Exception as e:
                print(f"[Firewall Auto-Update VoiceChat Rule Error] {e}")
            
    return {
        "rules": rules,
        "voicechat": vc_info,
        "server_port": server_port
    }

@fastapi_app.post("/api/server/{name}/firewall/rule")
async def create_firewall_rule(name: str, data: FirewallRuleCreate, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    protocol = data.protocol.strip().upper()
    if protocol not in ("TCP", "UDP"):
        raise HTTPException(status_code=400, detail="Protocol must be TCP or UDP")
        
    internal_port = data.internal_port
    if not (1 <= internal_port <= 65535):
        raise HTTPException(status_code=400, detail="Internal port must be between 1 and 65535")
        
    if protocol == "UDP":
        try:
            external_port = api.db.get_next_available_udp_port()
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
    else:
        external_port = data.external_port
        if external_port is None:
            external_port = internal_port
        elif not (1 <= external_port <= 65535):
            raise HTTPException(status_code=400, detail="External port must be between 1 and 65535 for TCP rules")
            
    # Check collision
    if api.db.check_external_port_collision(protocol, external_port):
        raise HTTPException(status_code=400, detail=f"Port collision: external port {external_port} ({protocol}) is already mapped")
        
    label = data.label.strip()
    
    rule_id = api.db.add_firewall_rule(name, protocol, data.enabled, internal_port, external_port, label)
    
    # If this is voicechat port, sync properties file immediately
    try:
        api.voicechat.sync_voicechat_properties_if_needed(name)
    except Exception as e:
        print(f"[VoiceChat Sync Error] {e}")
        
    return {
        "id": rule_id,
        "server_name": name,
        "protocol": protocol,
        "enabled": data.enabled,
        "internal_port": internal_port,
        "external_port": external_port,
        "label": label
    }

@fastapi_app.put("/api/server/{name}/firewall/rule/{rule_id}")
async def update_firewall_rule(name: str, rule_id: int, data: FirewallRuleUpdate, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    rule = api.db.get_firewall_rule(rule_id)
    if not rule or rule["server_name"] != name:
        raise HTTPException(status_code=404, detail="Firewall rule not found for this server")
        
    internal_port = data.internal_port
    if not (1 <= internal_port <= 65535):
        raise HTTPException(status_code=400, detail="Internal port must be between 1 and 65535")
        
    protocol = rule["protocol"]
    
    # Prevent changing internal port or protocol of the primary game port rule
    server_port = api.db.get_server_port_from_properties(name)
    is_primary = rule["label"] == "Primary Game Port" or (rule["protocol"] == "TCP" and rule["internal_port"] == server_port)
    
    # Prevent changing internal port or protocol of the Simple Voice Chat rule
    is_voicechat = rule["protocol"] == "UDP" and rule["label"].strip().lower() == "simple voice chat"
    
    if is_primary:
        if internal_port != server_port:
            raise HTTPException(status_code=400, detail="Cannot change the internal port of the primary game port rule.")
        label_to_save = "Primary Game Port"
    elif is_voicechat:
        vc = api.voicechat.detect_voicechat(name)
        vc_port = vc["current_port"] if (vc["detected"] and vc["current_port"]) else 24454
        if internal_port != vc_port:
            raise HTTPException(status_code=400, detail="Cannot change the internal port of the Simple Voice Chat rule. It must be loaded from voicechat properties.")
        label_to_save = "Simple Voice Chat"
    else:
        label_to_save = data.label.strip()
    
    if protocol == "TCP":
        external_port = data.external_port
        if external_port is None:
            external_port = internal_port
        elif not (1 <= external_port <= 65535):
            raise HTTPException(status_code=400, detail="External port must be between 1 and 65535 for TCP rules")
        # Check collision
        if api.db.check_external_port_collision("TCP", external_port, exclude_id=rule_id):
            raise HTTPException(status_code=400, detail=f"Port collision: external port {external_port} (TCP) is already mapped")
            
        api.db.update_firewall_rule(rule_id, data.enabled, internal_port, label_to_save, external_port)
    else:
        # For UDP, external port is FIXED
        api.db.update_firewall_rule(rule_id, data.enabled, internal_port, label_to_save)
        
    # Sync voicechat properties file immediately
    try:
        api.voicechat.sync_voicechat_properties_if_needed(name)
    except Exception as e:
        print(f"[VoiceChat Sync Error] {e}")
        
    return {"message": "Firewall rule updated successfully"}

@fastapi_app.delete("/api/server/{name}/firewall/rule/{rule_id}")
async def delete_firewall_rule(name: str, rule_id: int, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    rule = api.db.get_firewall_rule(rule_id)
    if not rule or rule["server_name"] != name:
        raise HTTPException(status_code=404, detail="Firewall rule not found for this server")
        
    # Prevent deleting primary server port rule
    server_port = api.db.get_server_port_from_properties(name)
    is_primary = rule["label"] == "Primary Game Port" or (rule["protocol"] == "TCP" and rule["internal_port"] == server_port)
    if is_primary:
        raise HTTPException(status_code=400, detail="Cannot delete the primary game port rule.")
        
    api.db.delete_firewall_rule(rule_id)
    
    # Sync voicechat properties file immediately (removes voicechat rule association)
    try:
        api.voicechat.sync_voicechat_properties_if_needed(name)
    except Exception as e:
        print(f"[VoiceChat Sync Error] {e}")
        
    return {"message": "Firewall rule deleted successfully"}

@fastapi_app.post("/api/server/{name}/firewall/apply")
async def apply_firewall_rules(name: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    # Check if the server is currently running
    status_info = api.post.server.run.get_server_status(name)
    is_running = False
    if isinstance(status_info, dict) and status_info.get("status") == "running":
        is_running = True

    # Recreate the server container (rebuild ports)
    result = await asyncio.to_thread(api.post.server.run.run_server, name, not is_running)
    await sio.emit("servers_updated", {})
    return {"message": result}

@fastapi_app.post("/api/server/{name}/firewall/quick-add-voicechat")
async def quick_add_voicechat_rule(name: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    # 1. Detect voicechat
    vc = api.voicechat.detect_voicechat(name)
    if not vc["detected"]:
        raise HTTPException(status_code=400, detail="Simple Voice Chat not detected on this server")
        
    # 2. Get active/default port
    internal_port = vc["current_port"] if vc["current_port"] else 24454
    
    # 3. Check duplicate rules
    rules = api.db.get_server_firewall_rules(name)
    for r in rules:
        if r["protocol"] == "UDP" and (r["label"].strip().lower() == "simple voice chat" or r["internal_port"] == internal_port):
            raise HTTPException(status_code=400, detail="A firewall rule for Simple Voice Chat already exists")
            
    # 4. Allocate UDP port
    try:
        external_port = api.db.get_next_available_udp_port()
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
        
    if api.db.check_external_port_collision("UDP", external_port):
        raise HTTPException(status_code=400, detail=f"UDP external port {external_port} is already in use")
        
    # 5. Create rule
    rule_id = api.db.add_firewall_rule(name, "UDP", True, internal_port, external_port, "Simple Voice Chat")
    
    # 6. Surgical write to properties
    try:
        server_info = api.db.get_server_info(name)
        hostname = server_info.get("hostname") if server_info else None
        voice_host = f"{hostname}:{external_port}" if hostname else f"<public-host>:{external_port}"
        
        api.voicechat.write_or_update_voicechat_properties(vc["config_path"], internal_port, voice_host)
    except Exception as prop_err:
        print(f"[VoiceChat Quick-Add Props Edit Error] {prop_err}")
        
    return {
        "id": rule_id,
        "server_name": name,
        "protocol": "UDP",
        "enabled": True,
        "internal_port": internal_port,
        "external_port": external_port,
        "label": "Simple Voice Chat"
    }

# ============================================================================
# Quick Settings Endpoints
# ============================================================================
@fastapi_app.get("/api/server/{name}/quick-settings")
async def get_server_quick_settings(name: str, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    import os
    server_local_path = os.path.abspath(os.path.join("data", "servers", name))
    props_path = os.path.join(server_local_path, "server.properties")
    
    props_dict = {}
    if os.path.exists(props_path):
        try:
            with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        key, val = stripped.split("=", 1)
                        props_dict[key.strip()] = val.strip()
        except Exception as e:
            print(f"[QuickSettings] Error reading server.properties: {e}")

    SUPPORTED_KEYS = {
        "difficulty": "easy",
        "enable-rcon": "false",
        "gamemode": "survival",
        "hardcore": "false",
        "level-name": "world",
        "level-seed": "",
        "level-type": "minecraft:normal",
        "max-players": "20",
        "motd": "A Minecraft Server",
        "online-mode": "true",
        "rcon.password": "admin",
        "rcon.port": "25575",
        "server-port": "25565",
        "simulation-distance": "10",
        "spawn-protection": "16",
        "view-distance": "10",
        "white-list": "false"
    }

    settings = {}
    for key, def_val in SUPPORTED_KEYS.items():
        val_str = props_dict.get(key, def_val)
        api_key = key.replace("-", "_").replace(".", "_")
        
        # Type conversions
        if key in ("enable-rcon", "hardcore", "online-mode", "white-list"):
            settings[api_key] = val_str.lower() == "true"
        elif key in ("max-players", "rcon.port", "server-port", "simulation-distance", "spawn-protection", "view-distance"):
            try:
                settings[api_key] = int(val_str)
            except ValueError:
                try:
                    settings[api_key] = int(def_val)
                except ValueError:
                    settings[api_key] = 0
        else:
            settings[api_key] = val_str

    # Check voicechat properties
    vc_data = api.voicechat.parse_voicechat_properties(name)
    
    return {
        **settings,
        "voicechat": vc_data
    }

@fastapi_app.put("/api/server/{name}/quick-settings")
async def update_server_quick_settings(name: str, data: QuickSettingsRequest, current_user: str = Depends(get_current_user)):
    name = name.strip()
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
        
    server_port = data.server_port
    if not (1 <= server_port <= 65535):
        raise HTTPException(status_code=400, detail="Server port must be between 1 and 65535")
        
    PROPERTY_MAPPING = {
        "difficulty": "difficulty",
        "enable_rcon": "enable-rcon",
        "gamemode": "gamemode",
        "hardcore": "hardcore",
        "level_name": "level-name",
        "level_seed": "level-seed",
        "level_type": "level-type",
        "max_players": "max-players",
        "motd": "motd",
        "online_mode": "online-mode",
        "rcon_password": "rcon.password",
        "rcon_port": "rcon.port",
        "server_port": "server-port",
        "simulation_distance": "simulation-distance",
        "spawn_protection": "spawn-protection",
        "view_distance": "view-distance",
        "white_list": "white-list"
    }

    # Extract all properties from payload
    new_props = {}
    for attr, prop_key in PROPERTY_MAPPING.items():
        val = getattr(data, attr)
        if val is not None:
            if isinstance(val, bool):
                new_props[prop_key] = "true" if val else "false"
            else:
                new_props[prop_key] = str(val)

    # 1. Write to server.properties
    try:
        import os
        import shutil
        server_local_path = os.path.abspath(os.path.join("data", "servers", name))
        props_path = os.path.join(server_local_path, "server.properties")
        os.makedirs(server_local_path, exist_ok=True)
        
        # Read existing properties to check if seed changed and get level-name
        old_seed = ""
        old_level_name = "world"
        
        if os.path.exists(props_path):
            with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        k, v = stripped.split("=", 1)
                        k = k.strip()
                        if k == "level-seed":
                            old_seed = v.strip()
                        elif k == "level-name":
                            old_level_name = v.strip()

        # Check if the seed has changed
        if "level-seed" in new_props:
            new_seed = new_props["level-seed"].strip()
            if old_seed != new_seed:
                # Delete all world folders!
                print(f"[QuickSettings] Seed changed for '{name}' (from '{old_seed}' to '{new_seed}'). Deleting world folders...")
                for folder in [old_level_name, f"{old_level_name}_nether", f"{old_level_name}_the_end"]:
                    world_folder_path = os.path.join(server_local_path, folder)
                    if os.path.exists(world_folder_path):
                        try:
                            if os.path.isdir(world_folder_path):
                                shutil.rmtree(world_folder_path)
                                print(f"[QuickSettings] Deleted folder: {world_folder_path}")
                            else:
                                os.remove(world_folder_path)
                        except Exception as delete_err:
                            print(f"[QuickSettings] Error deleting world path {world_folder_path}: {delete_err}")

        # Re-write the properties file preserving comments
        lines = []
        if os.path.exists(props_path):
            with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                
        new_lines = []
        updated_keys = set()
        
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, val = stripped.split("=", 1)
                key = key.strip()
                if key in new_props:
                    suffix = "\n" if not line.endswith("\r\n") else "\r\n"
                    new_lines.append(f"{key}={new_props[key]}{suffix}")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        # Append any new keys that weren't in the original file
        for key, val in new_props.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={val}\n")
                
        with open(props_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write server.properties: {e}")
        
    # Sync with DB servers table (get_server_port_from_properties executes DB update if different)
    api.db.get_server_port_from_properties(name)
    
    # Sync primary firewall rule in DB
    rules = api.db.get_server_firewall_rules(name)
    primary_rule = None
    for r in rules:
        if r["label"] == "Primary Game Port":
            primary_rule = r
            break
            
    if primary_rule:
        new_external = primary_rule["external_port"]
        if primary_rule["external_port"] == primary_rule["internal_port"]:
            new_external = server_port
        try:
            api.db.update_firewall_rule(
                primary_rule["id"],
                primary_rule["enabled"],
                server_port,
                "Primary Game Port",
                new_external
            )
        except Exception as e:
            print(f"[QuickSettings] Error syncing firewall rule in DB: {e}")
    else:
        try:
            api.db.add_firewall_rule(name, "TCP", True, server_port, server_port, "Primary Game Port")
        except Exception as e:
            print(f"[QuickSettings] Error creating firewall rule in DB: {e}")
            
    # 2. Write to voicechat-server.properties if provided
    if data.voicechat:
        updates = {}
        for key in ("port", "max_voice_distance", "whisper_distance", "enable_groups", "allow_recording", "spectator_interaction", "spectator_player_possession", "broadcast_range"):
            if key in data.voicechat:
                val = data.voicechat[key]
                if isinstance(val, bool):
                    updates[key] = "true" if val else "false"
                else:
                    updates[key] = str(val)
        if updates:
            try:
                api.voicechat.update_voicechat_properties_bulk(name, updates)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to update voicechat properties: {e}")
                
            # If voicechat port changed, sync database rule too immediately
            if "port" in updates:
                new_vc_port = int(updates["port"])
                vc_rule = None
                for r in rules:
                    if r["protocol"] == "UDP" and r["label"].strip().lower() == "simple voice chat":
                        vc_rule = r
                        break
                if vc_rule:
                    try:
                        api.db.update_firewall_rule(
                            vc_rule["id"],
                            vc_rule["enabled"],
                            new_vc_port,
                            "Simple Voice Chat"
                        )
                    except Exception as e:
                        print(f"[QuickSettings VoiceChat Sync Error] {e}")
                        
    return {"message": "Quick Settings updated successfully"}

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
