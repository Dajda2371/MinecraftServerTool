import os
import threading
import docker
import api.db
from api.post.server.mounts import (
    SERVER_DATA_VOLUME,
    write_volume_file,
    ensure_volume_directory,
    get_compose_labels,
    volume_subpath_mount
)

def enable_https_async(domain: str):
    """Starts the Nginx + Certbot HTTPS workflow in a background thread."""
    thread = threading.Thread(target=enable_https_workflow, args=(domain,), daemon=True)
    thread.start()

def enable_https_workflow(domain: str):
    """Executes Nginx config generation, container spawning, and Certbot verification."""
    client = docker.from_env()
    api.db.set_setting("https_status", "enabling")
    api.db.set_setting("https_domain", domain)
    api.db.set_setting("https_error", "")

    try:
        # 1. Ensure volume directories exist
        ensure_volume_directory(SERVER_DATA_VOLUME, "nginx/conf.d")
        ensure_volume_directory(SERVER_DATA_VOLUME, "nginx/letsencrypt")
        ensure_volume_directory(SERVER_DATA_VOLUME, "nginx/certbot_webroot")

        # 2. Write Nginx bootstrap configuration (HTTP only with acme mapping)
        bootstrap_conf = f"""server {{
    listen 80;
    server_name {domain};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        proxy_pass http://minecraft-server-tool:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Websocket support for console Socket.IO logs
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""
        write_volume_file(SERVER_DATA_VOLUME, "nginx/conf.d/default.conf", bootstrap_conf)

        # 3. Spawn/recreate Nginx container
        try:
            old_nginx = client.containers.get("mc-nginx")
            old_nginx.remove(force=True)
        except docker.errors.NotFound:
            pass

        print(f"[HTTPS] Starting Nginx bootstrap container for {domain}...")
        client.containers.run(
            image="nginx:alpine",
            name="mc-nginx",
            ports={
                '80/tcp': 80,
                '443/tcp': 443
            },
            mounts=[
                volume_subpath_mount(target="/etc/nginx/conf.d", volume_name=SERVER_DATA_VOLUME, subpath="nginx/conf.d"),
                volume_subpath_mount(target="/etc/letsencrypt", volume_name=SERVER_DATA_VOLUME, subpath="nginx/letsencrypt"),
                volume_subpath_mount(target="/var/www/certbot", volume_name=SERVER_DATA_VOLUME, subpath="nginx/certbot_webroot")
            ],
            network="mc-net",
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels=get_compose_labels("nginx-proxy")
        )

        # 4. Run Certbot container to obtain certificates
        try:
            old_certbot = client.containers.get("mc-certbot")
            old_certbot.remove(force=True)
        except docker.errors.NotFound:
            pass

        print(f"[HTTPS] Running Certbot verification for {domain}...")
        certbot_container = client.containers.run(
            image="certbot/certbot:latest",
            command=f"certonly --webroot -w /var/www/certbot -d {domain} --register-unsafely-without-email --agree-tos --non-interactive",
            name="mc-certbot",
            mounts=[
                volume_subpath_mount(target="/etc/letsencrypt", volume_name=SERVER_DATA_VOLUME, subpath="nginx/letsencrypt"),
                volume_subpath_mount(target="/var/www/certbot", volume_name=SERVER_DATA_VOLUME, subpath="nginx/certbot_webroot")
            ],
            network="mc-net",
            detach=True,
            labels=get_compose_labels("certbot-verify")
        )

        result = certbot_container.wait()
        exit_code = result.get("StatusCode", -1)
        logs = certbot_container.logs().decode("utf-8", errors="replace")

        try:
            certbot_container.remove()
        except Exception:
            pass

        if exit_code != 0:
            raise RuntimeError(f"Certbot validation failed (exit {exit_code}). Logs:\n{logs}")

        # 5. Write final SSL configuration
        ssl_conf = f"""server {{
    listen 80;
    server_name {domain};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    location / {{
        proxy_pass http://minecraft-server-tool:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Websocket support for console Socket.IO logs
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""
        write_volume_file(SERVER_DATA_VOLUME, "nginx/conf.d/default.conf", ssl_conf)

        # 6. Reload Nginx
        nginx_container = client.containers.get("mc-nginx")
        nginx_container.exec_run("nginx -s reload")

        api.db.set_setting("https_status", "enabled")
        print(f"[HTTPS] Nginx successfully reloaded with SSL certificates for {domain}!")

    except Exception as e:
        error_msg = str(e)
        print(f"[HTTPS Error] {error_msg}")
        api.db.set_setting("https_status", "failed")
        api.db.set_setting("https_error", error_msg)

def disable_https():
    """Stops the reverse proxy Nginx container and cleans database settings."""
    client = docker.from_env()
    api.db.set_setting("https_status", "disabled")
    api.db.set_setting("https_domain", "")
    api.db.set_setting("https_error", "")

    try:
        nginx = client.containers.get("mc-nginx")
        nginx.remove(force=True)
        print("[HTTPS] Nginx container removed.")
    except docker.errors.NotFound:
        pass
    except Exception as e:
        print(f"[HTTPS Warning] Could not remove Nginx container: {e}")

def get_https_status():
    """Returns the current state, active domain, and any errors of the HTTPS setup."""
    status = api.db.get_setting("https_status", "disabled")
    domain = api.db.get_setting("https_domain", "")
    error = api.db.get_setting("https_error", "")
    return {
        "status": status,
        "domain": domain,
        "error": error
    }

def check_https_on_startup():
    """Verifies that Nginx is running if HTTPS is set to active."""
    status_info = get_https_status()
    if status_info["status"] == "enabled" and status_info["domain"]:
        print(f"[HTTPS Startup Check] HTTPS is active for {status_info['domain']}. Verifying Nginx...")
        client = docker.from_env()
        try:
            nginx = client.containers.get("mc-nginx")
            if nginx.status != "running":
                nginx.start()
                print("[HTTPS Startup Check] Nginx container started.")
        except docker.errors.NotFound:
            print("[HTTPS Startup Check] Nginx container not found. Bootstrapping HTTPS...")
            enable_https_async(status_info["domain"])
        except Exception as e:
            print(f"[HTTPS Startup Check Warning] {e}")
