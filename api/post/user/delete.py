import api.db

def delete_user(username):
    if api.db.delete_user(username):
        return f"User '{username}' deleted successfully."
    else:
        return f"User '{username}' not found."
