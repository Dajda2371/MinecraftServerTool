import api.db

def add_owner(server_name, username):
    success, message = api.db.add_server_owner(server_name, username)
    return message
