import api.db

def list_users():
    users = api.db.get_users()
    if users:
        return "Users: " + ", ".join(users)
    else:
        return "No users found."
