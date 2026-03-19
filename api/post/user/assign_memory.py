import api.db

def assign_memory(username, limit_mb):
    if api.db.update_user_memory(username, limit_mb):
        return f"Successfully assigned {limit_mb} MB memory to user '{username}'."
    return f"Failed to assign memory. User '{username}' may not exist."
