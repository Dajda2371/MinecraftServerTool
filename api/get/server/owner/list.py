import api.db

def list_owners(server_name):
    owners = api.db.get_server_owners(server_name)
    if owners:
        return f"Owners of {server_name}: " + ", ".join(owners)
    else:
        return f"No owners found for {server_name}."
