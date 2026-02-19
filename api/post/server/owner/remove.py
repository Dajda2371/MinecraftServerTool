import api.db

def remove_owner(server_name, username):
    success, message = api.db.remove_server_owner(server_name, username)
    return message
