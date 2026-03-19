import api.db

def reset_password(username, new_password):
    if api.db.set_user_password(username, new_password):
        return f"Password successfully updated for user '{username}'."
    return f"Failed to update password. User '{username}' may not exist."
