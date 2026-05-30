import os
import threading
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Cookie, Response, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

# Import existing backend modules
import api.db
import api.auth
import api.infrared
import api.post.server.create
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

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database on startup
    api.db.init_db()
    
    # Generate Infrared config files
    try:
        api.infrared.generate_infrared_config()
        api.infrared.generate_proxy_files()
        print("[Startup] Infrared configuration generated.")
    except Exception as e:
        print(f"[Startup] Warning: Could not generate Infrared config: {e}")
    yield

# Initialize FastAPI App
app = FastAPI(title="Minecraft Server Manager", lifespan=lifespan)

# --- Exception Handlers for Frontend Compatibility ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

@app.exception_handler(RequestValidationError)
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

@app.exception_handler(Exception)
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

# ============================================================================
# Auth Endpoints
# ============================================================================
@app.post("/api/auth/login")
async def login(data: LoginRequest, response: Response):
    username = data.username.strip()
    password = data.password.strip()
    if api.db.verify_user_password(username, password):
        token = api.auth.create_session(username)
        response.set_cookie(key="session_id", value=token, path="/", httponly=True)
        return {"message": "Success", "username": username}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/logout")
async def logout(response: Response, session_id: Optional[str] = Cookie(default=None)):
    if session_id:
        api.auth.delete_session(session_id)
    response.delete_cookie(key="session_id", path="/")
    return {"message": "Logged out"}

@app.get("/api/auth/me")
async def auth_me(current_user: str = Depends(get_current_user)):
    user_info = api.db.get_user_info(current_user)
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    return user_info

# ============================================================================
# User Endpoints (Admin Only)
# ============================================================================
@app.get("/api/users")
async def get_users(admin_user: str = Depends(get_admin_user)):
    return {"users": [api.db.get_user_info(u) for u in api.db.get_users()]}

@app.post("/api/user/add")
async def user_add(data: UserRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.create.create_user(username)
    return {"message": res}

@app.post("/api/user/remove")
async def user_remove(data: UserRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.delete.delete_user(username)
    return {"message": res}

@app.post("/api/user/assign")
async def user_assign(data: AssignMemoryRequest, admin_user: str = Depends(get_admin_user)):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    res = api.post.user.assign_memory.assign_memory(username, data.limit_mb)
    return {"message": res}

@app.post("/api/user/reset")
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
@app.get("/api/servers")
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

@app.get("/api/server/{name}")
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

@app.get("/api/server/{name}/creation-logs")
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

@app.post("/api/server/create", status_code=202)
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
    return {"message": f"Creation of '{name}' started in background."}

@app.post("/api/server/agree-eula")
async def agree_eula(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = api.post.server.run.agree_to_eula(name)
    return {"message": result}

@app.post("/api/server/run")
async def run_server(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = api.post.server.run.run_server(name)
    return {"message": result}

@app.post("/api/server/stop")
async def stop_server(data: ServerNameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = api.post.server.stop.stop_server(name) 
    return {"message": result}

@app.post("/api/server/delete")
async def delete_server(data: DeleteServerRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    result = api.post.server.delete.delete_server(name, remove_data=data.remove_data)
    return {"message": result}

@app.post("/api/server/hostname")
async def server_hostname(data: UpdateHostnameRequest, current_user: str = Depends(get_current_user)):
    name = data.name.strip()
    hostname = data.hostname.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    
    if not check_server_access(name, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Allow empty string to unset hostname
    result = api.post.server.hostname.update_hostname(name, hostname)
    return {"message": result}

@app.post("/api/server/memory")
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
        return {"message": result}

# ============================================================================
# Proxy (Infrared) Control & Status (Admin Only)
# ============================================================================
@app.get("/api/proxy/status")
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

@app.get("/api/proxy/routes")
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

@app.post("/api/proxy/start")
async def proxy_start(admin_user: str = Depends(get_admin_user)):
    api.infrared.reload_proxy_config()
    import docker as docker_mod
    try:
        client = docker_mod.from_env()
        container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
        if container.status != "running":
            container.start()
        return {"message": "Infrared container started; config reloaded."}
    except docker_mod.errors.NotFound:
        return {"message": "Infrared config written; container not found (start via docker-compose)."}

@app.post("/api/proxy/stop")
async def proxy_stop(admin_user: str = Depends(get_admin_user)):
    import docker as docker_mod
    try:
        client = docker_mod.from_env()
        container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
        container.stop(timeout=10)
        return {"message": "Infrared container stopped."}
    except docker_mod.errors.NotFound:
        return {"message": "Infrared container not found."}

@app.post("/api/proxy/reload")
async def proxy_reload(admin_user: str = Depends(get_admin_user)):
    api.infrared.reload_proxy_config()
    return {"message": "Infrared config reloaded"}

# ============================================================================
# Static Files & View Routing
# ============================================================================
@app.get("/")
async def serve_index():
    return FileResponse(frontend_dir / "index.html")

@app.get("/login.html")
async def serve_login():
    return FileResponse(frontend_dir / "login.html")

@app.get("/infrared")
async def serve_infrared(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return RedirectResponse(url="/login.html", status_code=302)
    user = api.auth.get_session_user(session_id)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    if user != 'admin':
        raise HTTPException(status_code=403, detail="Access denied: Admin required")
    return FileResponse(frontend_dir / "infrared.html")

@app.get("/api.js")
async def serve_api_js():
    path = frontend_dir / "api.js"
    if path.exists():
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Not Found")

# Mount Static subfolders if they exist
if (frontend_dir / "css").exists():
    app.mount("/css", StaticFiles(directory=str(frontend_dir / "css")), name="css")

if (frontend_dir / "js").exists():
    app.mount("/js", StaticFiles(directory=str(frontend_dir / "js")), name="js")

if (frontend_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")
