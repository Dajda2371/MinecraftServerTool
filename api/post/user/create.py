import api.db

def create_user(username):
    if api.db.add_user(username):
        return f"User '{username}' created successfully."
    else:
        return f"User '{username}' already exists."
