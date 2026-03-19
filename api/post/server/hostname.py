"""
Update a Minecraft server's routed hostname and reload Velocity configuration.
"""

from api.db import update_server_hostname as db_update_hostname
from api.velocity import reload_velocity_config

def update_hostname(server_name, new_hostname):
    """
    Updates the routing hostname for a server and restarts the Velocity proxy.
    """
    success, message = db_update_hostname(server_name, new_hostname)
    
    if success:
        try:
            reload_velocity_config()
            return f"Hostname updated to '{new_hostname}' and Velocity reloaded."
        except Exception as e:
            return f"Hostname updated in DB, but failed to reload Velocity: {e}"
    else:
        return message
