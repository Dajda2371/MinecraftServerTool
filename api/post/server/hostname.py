"""
Update a Minecraft server's routed hostname and reload Infrared configuration.
"""

from api.db import update_server_hostname as db_update_hostname
from api.infrared import reload_proxy_config

def update_hostname(server_name, new_hostname):
    """
    Updates the routing hostname for a server and reloads the Infrared proxy.
    """
    success, message = db_update_hostname(server_name, new_hostname)

    if success:
        try:
            reload_proxy_config()
            return f"Hostname updated to '{new_hostname}' and Infrared reloaded."
        except Exception as e:
            return f"Hostname updated in DB, but failed to reload Infrared: {e}"
    else:
        return message
