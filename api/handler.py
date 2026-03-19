from http.server import SimpleHTTPRequestHandler
import json

import api.post.server.create
import api.post.server.run
import api.post.server.stop
import api.post.server.delete
import api.post.server.owner
import api.post.server.hostname
import api.db
import api.velocity


class Handler(SimpleHTTPRequestHandler):

    def _send_json(self, status, data):
        """Helper to send a JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

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
            self.path in ["/", "/api.js"]
            or self.path.startswith("/assets/")
            or self.path.startswith("/js/")
            or self.path.startswith("/css/")
        ):
            if self.path == "/":
                self.path = '/index.html'
            return super().do_GET()

        # --- API: List all servers ---
        elif self.path == "/api/servers":
            servers = api.db.get_all_servers()
            # Augment with container status
            for srv in servers:
                try:
                    status_info = api.post.server.run.get_server_status(srv["name"])
                    if isinstance(status_info, dict):
                        srv["status"] = status_info.get("status", "unknown")
                    else:
                        srv["status"] = "unknown"
                except Exception:
                    srv["status"] = "unknown"
            return self._send_json(200, {"servers": servers})

        # --- API: Get single server ---
        elif self.path.startswith("/api/server/"):
            server_name = self.path.split("/api/server/")[1]
            info = api.db.get_server_info(server_name)
            if info:
                try:
                    status_info = api.post.server.run.get_server_status(server_name)
                    if isinstance(status_info, dict):
                        info["status"] = status_info.get("status", "unknown")
                    else:
                        info["status"] = "unknown"
                except Exception:
                    info["status"] = "unknown"
                return self._send_json(200, info)
            else:
                return self._send_json(404, {"error": f"Server '{server_name}' not found"})

        # --- API: Velocity status ---
        elif self.path == "/api/velocity/status":
            import os
            pid_file = api.velocity.VELOCITY_PID_FILE
            running = False
            pid = None
            if os.path.exists(pid_file):
                with open(pid_file, "r") as f:
                    pid = f.read().strip()
                try:
                    os.kill(int(pid), 0)
                    running = True
                except (ProcessLookupError, ValueError):
                    running = False
            return self._send_json(200, {"running": running, "pid": pid})

        else:
            return self.send_error(404, "Not Found")

    def do_POST(self):
        # --- Create server ---
        if self.path == "/api/server/create":
            data = self._read_json()
            name = data.get("name", "").strip()
            server_type = data.get("type", "spigot").strip()
            version = data.get("version", "").strip()
            owner = data.get("owner", "admin").strip()

            if not name or not version:
                return self._send_json(400, {"error": "name and version are required"})

            result = api.post.server.create.create_server(name, server_type, version, owner=owner)
            return self._send_json(200, {"message": result})

        # --- Run (start) server ---
        elif self.path == "/api/server/run":
            data = self._read_json()
            name = data.get("name", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            result = api.post.server.run.run_server(name)
            return self._send_json(200, {"message": result})

        # --- Stop server ---
        elif self.path == "/api/server/stop":
            data = self._read_json()
            name = data.get("name", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            result = api.post.server.stop.stop_server(name)
            return self._send_json(200, {"message": result})

        # --- Delete server ---
        elif self.path == "/api/server/delete":
            data = self._read_json()
            name = data.get("name", "").strip()
            remove_data = data.get("remove_data", False)
            if not name:
                return self._send_json(400, {"error": "name is required"})
            result = api.post.server.delete.delete_server(name, remove_data=remove_data)
            return self._send_json(200, {"message": result})

        # --- Update Hostname ---
        elif self.path == "/api/server/hostname":
            data = self._read_json()
            name = data.get("name", "").strip()
            hostname = data.get("hostname", "").strip()
            if not name:
                return self._send_json(400, {"error": "name is required"})
            
            # Allow empty string to unset hostname
            result = api.post.server.hostname.update_hostname(name, hostname)
            return self._send_json(200, {"message": result})

        # --- Velocity control ---
        elif self.path == "/api/velocity/start":
            api.velocity.download_velocity()
            api.velocity.start_velocity()
            return self._send_json(200, {"message": "Velocity started"})

        elif self.path == "/api/velocity/stop":
            api.velocity.stop_velocity()
            return self._send_json(200, {"message": "Velocity stopped"})

        elif self.path == "/api/velocity/reload":
            api.velocity.reload_velocity_config()
            return self._send_json(200, {"message": "Velocity config reloaded"})

        else:
            return self.send_error(404, "Not Found")