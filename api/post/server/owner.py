import api.db

def update_owner(server_name, owner_name):
    success, message = api.db.set_server_owner(server_name, owner_name)
    return message
