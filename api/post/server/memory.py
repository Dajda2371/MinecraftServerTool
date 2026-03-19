import api.db

def assign_memory(server_name, memory_mb, requesting_user):
    # Get user info and total memory allowed
    user_info = api.db.get_user_info(requesting_user)
    if not user_info:
        return f"User '{requesting_user}' not found."
    memory_limit = user_info['memory_limit']
    
    # Get all servers owned by the user
    servers = api.db.get_all_servers()
    user_servers = [s for s in servers if s['owner'] == requesting_user]
    
    # Find current server allocating to
    current_server = next((s for s in user_servers if s['name'] == server_name), None)
    
    # If admin is modifying an admin server, admin has bypass limit, but normally everyone is checked.
    if requesting_user != 'admin':
        if not current_server:
            # Maybe admin allocating to someone else's server? If the user isn't admin and doesn't own it, deny.
            return f"Server '{server_name}' not found or you don't own it."
        
        # Calculate memory used by other servers owned by the user
        other_memory_used = sum(s.get('memory_mb', 1024) for s in user_servers if s['name'] != server_name)
        
        if (other_memory_used + memory_mb) > memory_limit:
            return f"Cannot allocate {memory_mb} MB. Limit ({memory_limit} MB) will be exceeded. Used elsewhere: {other_memory_used} MB."

    if api.db.update_server_memory(server_name, memory_mb):
        return f"Successfully assigned {memory_mb} MB to server '{server_name}'. Changes take effect on next start."
    return f"Failed to assign memory to '{server_name}'."
