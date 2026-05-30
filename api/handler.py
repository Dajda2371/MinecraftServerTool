from http.server import SimpleHTTPRequestHandler
import json

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
import api.db
import api.infrared
import api.auth


class Handler(SimpleHTTPRequestHandler):

    def _send_json(self, status, payload, cookies=None):
        """Helper to send JSON response."""
        response_body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        if cookies:
            for name, val in cookies.items():
                if val is None:
                    # expire cookie
                    self.send_header('Set-Cookie', f"{name}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")
                else:
                    self.send_header('Set-Cookie', f"{name}={val}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(response_body)

    def _get_current_user(self):
        cookies = api.auth.parse_cookies(self.headers)
        if 'session_id' in cookies:
            return api.auth.get_session_user(cookies['session_id'])
        return None

    def _read_json(self):
        """Read and parse JSON from POST body."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw)

    def do_GET(self):
        # --- Static files ---
        if (
            self.path in ["/", "/api.js", "/login.html"]
            or self.path.startswith("/assets/")
            or self.path.startswith("/js/")
            or self.path.startswith("/css/")
        ):
            if self.path == "/":
                self.path = '/index.html'
            return super().do_GET()

        # --- API: Auth and Server Listing ---
        elif self.path == '/api/auth/me':
            user = self._get_current_user()
            if not user:
                return self._send_json(401, {"error": "Not logged in"})
            user_info = api.db.get_user_info(user)
            return self._send_json(200, user_info)
            
        elif self.path == '/api/users':
            user = self._get_current_user()
            if user != 'admin':
                return self._send_json(403, {"error": "Admin required"})
            return self._send_json(200, {"users": [api.db.get_user_info(u) for u in api.db.get_users()]})

        elif self.path == '/api/servers':
            user = self._get_current_user()
            if not user:
                return self._send_json(401, {"error": "Not logged in"})
            
            servers = api.db.get_all_servers()
            
            # Filter servers if not admin
            if user != 'admin':
                servers = [s for s in servers if s['owner'] == user]
                
            for server in servers:
                status = api.post.server.run.get_server_status(server["name"])
                if isinstance(status, dict):
                    server["status"] = status.get("status", "UNKNOWN")
                else:
                    server["status"] = "UNKNOWN"
            return self._send_json(200, {"servers": servers})

        elif self.path.startswith('/api/server/') and self.path.endswith('/creation-logs'):
            user = self._get_current_user()
            if not user:
                return self._send_json(401, {"error": "Not logged in"})
                
            parts = self.path.split('/')
            name = parts[-2]
            server = api.db.get_server_info(name)
            
            if not server:
                return self._send_json(404, {"error": "Server not found"})
                
            if user != 'admin' and server['owner'] != user:
                return self._send_json(403, {"error": "Access denied"})
                
            import os
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
                
            return self._send_json(200, {"logs": log_content})

        elif self.path.startswith('/api/server/'):
            user = self._get_current_user()
            if not user:
                return self._send_json(401, {"error": "Not logged in"})
                
            name = self.path.split('/')[-1]
            server = api.db.get_server_info(name)
            
            if not server:
                return self._send_json(404, {"error": "Server not found"})
                
            if user != 'admin' and server['owner'] != user:
                return self._send_json(403, {"error": "Access denied"})
                
            status = api.post.server.run.get_server_status(name)
            if isinstance(status, dict):
                server["status"] = status.get("status", "UNKNOWN")
            else:
                server["status"] = "UNKNOWN"
            return self._send_json(200, server)

        # --- API: Proxy (Infrared) status ---
        elif self.path == "/api/proxy/status":
            import docker as docker_mod
            try:
                client = docker_mod.from_env()
                container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
                running = container.status == "running"
                return self._send_json(200, {"running": running, "container": container.status})
            except docker_mod.errors.NotFound:
                return self._send_json(200, {"running": False, "container": "not found"})
            except Exception as e:
                return self._send_json(200, {"running": False, "container": str(e)})

        else:
            return self.send_error(404, "Not Found")

    def do_POST(self):
        """Handle POST requests (API endpoints)"""
        
        # --- Auth ---
        if self.path == '/api/auth/login':
            data = self._read_json()
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()
            if api.db.verify_user_password(username, password):
                token = api.auth.create_session(username)
                return self._send_json(200, {"message": "Success", "username": username}, cookies={'session_id': token})
            else:
                return self._send_json(401, {"error": "Invalid credentials"})
                
        elif self.path == '/api/auth/logout':
            cookies = api.auth.parse_cookies(self.headers)
            if 'session_id' in cookies:
                api.auth.delete_session(cookies['session_id'])
            return self._send_json(200, {"message": "Logged out"}, cookies={'session_id': None})
            
        # Ensure user is logged in for all below
        user = self._get_current_user()
        if not user:
            return self._send_json(401, {"error": "Authentication required"})
            
        # Check permissions logic handler
        def check_server_access(server_name):
            if user == 'admin': return True
            info = api.db.get_server_info(server_name)
            if info and info['owner'] == user: return True
            return False

        # --- Create server ---
        if self.path == "/api/server/create":
            data = self._read_json()
            name = data.get("name", "").strip()
            server_type = data.get("type", "spigot").strip()
            version = data.get("version", "").strip()
            owner = data.get("owner", "admin").strip()

            if not name or not version:
                return self._send_json(400, {"error": "name and version are required"})

            # Only admin can create servers for other owners
            if user != 'admin' and owner != user:
                return self._send_json(403, {"error": "Access denied: Cannot create server for another user"})

            # If not admin, force owner to current user
            if user != 'admin':
                owner = user

            # Parse and validate memory_mb
            try:
                memory_mb = int(data.get("memory_mb", 1024))
            except (TypeError, ValueError):
                return self._send_json(400, {"error": "memory_mb must be an integer"})

            if memory_mb < 512:
                return self._send_json(400, {"error": "memory_mb must be at least 512"})

            # Validate against user memory limit (admin bypasses)
            if user != 'admin':
                user_info = api.db.get_user_info(owner)
                if user_info:
                    memory_limit = user_info['memory_limit']
                    servers = api.db.get_all_servers()
                    used = sum(s.get('memory_mb', 1024) for s in servers if s['owner'] == owner)
                    if (used + memory_mb) > memory_limit:
                        return self._send_json(400, {
                            "error": f"Cannot allocate {memory_mb} MB. Limit: {memory_limit} MB, already used: {used} MB."
                        })

            import threading
            threading.Thread(
                target=api.post.server.create.create_server,
                args=(name, server_type, version),
                kwargs={"owner": owner, "memory_mb": memory_mb},
                daemon=True
            ).start()
            return self._send_json(202, {"message": f"Creation of '{name}' started in background."})

        # --- Run (start) server ---
        elif self.path == "/api/server/run":
            data = self._read_json()
            name = data.get("name", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            
            if not check_server_access(name):
                return self._send_json(403, {"error": "Access denied"})

            result = api.post.server.run.run_server(name)
            return self._send_json(200, {"message": result})

        # --- Stop server ---
        elif self.path == "/api/server/stop":
            data = self._read_json()
            name = data.get("name", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            
            if not check_server_access(name):
                return self._send_json(403, {"error": "Access denied"})

            result = api.post.server.stop.stop_server(name) 
            return self._send_json(200, {"message": result})

        # --- Delete server ---
        elif self.path == "/api/server/delete":
            data = self._read_json()
            name = data.get("name", "").strip()
            remove_data = data.get("remove_data", False)
            if not name:
                return self._send_json(400, {"error": "name is required"})
            
            if not check_server_access(name):
                return self._send_json(403, {"error": "Access denied"})

            result = api.post.server.delete.delete_server(name, remove_data=remove_data)
            return self._send_json(200, {"message": result})

        # --- Update Hostname ---
        elif self.path == "/api/server/hostname":
            data = self._read_json()
            name = data.get("name", "").strip()
            hostname = data.get("hostname", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            
            if not check_server_access(name):
                return self._send_json(403, {"error": "Access denied"})
            
            # Allow empty string to unset hostname
            result = api.post.server.hostname.update_hostname(name, hostname)
            return self._send_json(200, {"message": result})

        # --- Update Server Memory ---
        elif self.path == "/api/server/memory":
            data = self._read_json()
            name = data.get("name", "").strip()
            memory_mb = data.get("memory_mb")
            
            if not name or memory_mb is None:
                return self._send_json(400, {"error": "name and memory_mb are required"})
            
            if not check_server_access(name):
                return self._send_json(403, {"error": "Access denied"})
            
            try:
                memory_mb = int(memory_mb)
            except ValueError:
                return self._send_json(400, {"error": "memory_mb must be an integer"})
                
            result = api.post.server.memory.assign_memory(name, memory_mb, user)
            if "Failed" in result or "exceeded" in result or "not found" in result:
                return self._send_json(400, {"error": result})
            else:
                return self._send_json(200, {"message": result})

        # --- User Management (Admin Only) ---
        elif self.path.startswith("/api/user/"):
            if user != 'admin':
                return self._send_json(403, {"error": "Admin required"})
                
            data = self._read_json()
            username = data.get("username", "").strip()
            if not username:
                return self._send_json(400, {"error": "username is required"})
                
            if self.path == "/api/user/add":
                res = api.post.user.create.create_user(username)
                return self._send_json(200, {"message": res})
                
            elif self.path == "/api/user/remove":
                res = api.post.user.delete.delete_user(username)
                return self._send_json(200, {"message": res})
                
            elif self.path == "/api/user/assign":
                limit_mb = data.get("limit_mb")
                try: limit_mb = int(limit_mb)
                except (ValueError, TypeError): return self._send_json(400, {"error": "limit_mb must be an integer"})
                res = api.post.user.assign_memory.assign_memory(username, limit_mb)
                return self._send_json(200, {"message": res})
                
            elif self.path == "/api/user/reset":
                new_password = data.get("new_password", "").strip()
                res = api.post.user.reset_password.reset_password(username, new_password)
                return self._send_json(200, {"message": res})

        # --- Proxy (Infrared) control (Admin Only) ---
        elif self.path.startswith("/api/proxy/"):
            if user != 'admin':
                return self._send_json(403, {"error": "Admin required"})

            if self.path == "/api/proxy/start":
                # Infrared is managed by docker-compose; this just ensures the
                # config is up to date and nudges the container back to running
                # if it's stopped.
                api.infrared.reload_proxy_config()
                import docker as docker_mod
                try:
                    client = docker_mod.from_env()
                    container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
                    if container.status != "running":
                        container.start()
                    return self._send_json(200, {"message": "Infrared container started; config reloaded."})
                except docker_mod.errors.NotFound:
                    return self._send_json(200, {"message": "Infrared config written; container not found (start via docker-compose)."})

            elif self.path == "/api/proxy/stop":
                import docker as docker_mod
                try:
                    client = docker_mod.from_env()
                    container = client.containers.get(api.infrared.INFRARED_CONTAINER_NAME)
                    container.stop(timeout=10)
                    return self._send_json(200, {"message": "Infrared container stopped."})
                except docker_mod.errors.NotFound:
                    return self._send_json(200, {"message": "Infrared container not found."})

            elif self.path == "/api/proxy/reload":
                api.infrared.reload_proxy_config()
                return self._send_json(200, {"message": "Infrared config reloaded"})

        else:
            return self.send_error(404, "Not Found")