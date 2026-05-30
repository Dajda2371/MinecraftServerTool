import os
import psycopg2
from psycopg2 import errors as pg_errors

# ---------------------------------------------------------------------------
# Connection configuration
# ---------------------------------------------------------------------------
# All settings are read from the environment so the same image works in local
# Compose, CI, and production. Defaults match docker-compose.yml.
# ---------------------------------------------------------------------------

DB_HOST = os.environ.get("POSTGRES_HOST", "postgres")
DB_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "mcserver")
DB_USER = os.environ.get("POSTGRES_USER", "mcserver")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "mcserver")


def _connect():
    """Open a new connection to the PostgreSQL database."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def init_db():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            owner TEXT DEFAULT 'admin',
            type TEXT,
            version TEXT,
            jar_path TEXT,
            port INTEGER DEFAULT 25565,
            hostname TEXT,
            container_name TEXT,
            memory_mb INTEGER DEFAULT 1024
        )
    ''')

    # Column migrations — PostgreSQL supports IF [NOT] EXISTS on ADD/DROP.
    cursor.execute("ALTER TABLE servers ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 25565")
    cursor.execute("ALTER TABLE servers ADD COLUMN IF NOT EXISTS hostname TEXT")
    cursor.execute("ALTER TABLE servers ADD COLUMN IF NOT EXISTS container_name TEXT")
    cursor.execute("ALTER TABLE servers ADD COLUMN IF NOT EXISTS memory_mb INTEGER DEFAULT 1024")
    # Drop legacy column: forwarding_secret was used for Velocity modern
    # forwarding. Infrared does not require it.
    cursor.execute("ALTER TABLE servers DROP COLUMN IF EXISTS forwarding_secret")

    # Migrate existing servers to use standard port 25565
    # (each container has its own IP, so no port conflicts)
    cursor.execute("UPDATE servers SET port = 25565 WHERE port != 25565")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT,
            memory_limit INTEGER DEFAULT 4096
        )
    ''')

    # Users table column migrations
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password TEXT")
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS memory_limit INTEGER DEFAULT 4096")

    # Check if admin user exists in the database
    cursor.execute("SELECT password FROM users WHERE username = %s", ('admin',))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO users (username, password, memory_limit) VALUES (%s, %s, %s)",
            ('admin', 'admin', 8192),
        )
        print("Initialized default 'admin' user with password 'admin'.")
    else:
        # If admin exists but has no password (or empty), update it to 'admin'
        stored_password = row[0]
        if not stored_password:
            cursor.execute(
                "UPDATE users SET password = %s WHERE username = %s",
                ('admin', 'admin'),
            )
            print("Updated default 'admin' user password to 'admin'.")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def set_user_password(username, password):
    init_db()
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()

    if user:
        cursor.execute("UPDATE users SET password = %s WHERE username = %s", (password, username))
        conn.commit()
        conn.close()
        return True
    else:
        conn.close()
        return False


def get_user_info(username):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT username, memory_limit FROM users WHERE username = %s", (username,))
    data = cursor.fetchone()
    conn.close()
    if data:
        return {"username": data[0], "memory_limit": data[1]}
    return None


def update_user_memory(username, limit_mb):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET memory_limit = %s WHERE username = %s", (limit_mb, username))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def verify_user_password(username, password):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
    data = cursor.fetchone()
    conn.close()

    if data:
        stored_password = data[0]
        # For simplicity, using plain text representation or hashing.
        # In this tool setting password function didn't hash previously.
        # We will check if it matches literally or both are none/empty.
        if password == stored_password:
            return True
        elif not stored_password and not password:
            return True
    return False


def update_server_info(name, owner, type, version, jar_path, port=None, hostname=None, container_name=None, memory_mb=None):
    init_db()
    conn = _connect()
    cursor = conn.cursor()

    # Check if exists
    cursor.execute(
        "SELECT id, port, hostname, container_name, memory_mb FROM servers WHERE name = %s",
        (name,),
    )
    data = cursor.fetchone()

    if data:
        # If values provided, update them, otherwise keep current
        new_port = port if port is not None else data[1]
        new_hostname = hostname if hostname is not None else data[2]
        new_container = container_name if container_name is not None else data[3]
        new_memory = memory_mb if memory_mb is not None else data[4]
        cursor.execute('''
            UPDATE servers
            SET owner = %s, type = %s, version = %s, jar_path = %s, port = %s,
                hostname = %s, container_name = %s, memory_mb = %s
            WHERE name = %s
        ''', (owner, type, version, jar_path, new_port, new_hostname, new_container, new_memory, name))
    else:
        # If it doesn't exist, only insert if it's in a starting/creating state.
        # If it's a finished jar_path, it means the server was cancelled/deleted during creation.
        if jar_path not in ("BUILDING...", "DOWNLOADING..."):
            print(f"[DB] Server '{name}' was deleted/cancelled during creation. Skipping insert.")
            conn.close()
            return

        if port is None:
            port = 25565

        # Generate container name if not provided
        if container_name is None:
            container_name = f"mc-{name}"

        if memory_mb is None:
            memory_mb = 1024

        cursor.execute('''
            INSERT INTO servers (name, owner, type, version, jar_path, port, hostname, container_name, memory_mb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (name, owner, type, version, jar_path, port, hostname, container_name, memory_mb))

    conn.commit()
    conn.close()


def get_server_info(name):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, owner, type, version, jar_path, port, hostname, container_name, memory_mb "
        "FROM servers WHERE name = %s",
        (name,),
    )
    data = cursor.fetchone()
    conn.close()
    if data:
        return {
            "name": data[0],
            "owner": data[1],
            "type": data[2],
            "version": data[3],
            "jar_path": data[4],
            "port": data[5],
            "hostname": data[6],
            "container_name": data[7],
            "memory_mb": data[8],
        }
    return None


def get_all_servers():
    """Return a list of all server info dicts."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, owner, type, version, jar_path, port, hostname, container_name, memory_mb FROM servers"
    )
    rows = cursor.fetchall()
    conn.close()
    servers = []
    for data in rows:
        servers.append({
            "name": data[0],
            "owner": data[1],
            "type": data[2],
            "version": data[3],
            "jar_path": data[4],
            "port": data[5],
            "hostname": data[6],
            "container_name": data[7],
            "memory_mb": data[8],
        })
    return servers


def delete_server(name):
    """Delete a server from the database."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM servers WHERE name = %s", (name,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_user(username):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username) VALUES (%s)", (username,))
        conn.commit()
        return True
    except pg_errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_user(username):
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = %s", (username,))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_users():
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def set_server_owner(server_name, owner_name):
    init_db()
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM servers WHERE name = %s", (server_name,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return False, "Server not found."

    cursor.execute("SELECT id FROM users WHERE username = %s", (owner_name,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, f"User '{owner_name}' not found."

    cursor.execute("UPDATE servers SET owner = %s WHERE name = %s", (owner_name, server_name))
    conn.commit()
    conn.close()
    return True, f"Owner of server '{server_name}' updated to '{owner_name}'."


def update_server_hostname(server_name, hostname):
    """Update a server's hostname."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM servers WHERE name = %s", (server_name,))
    if not cursor.fetchone():
        conn.close()
        return False, f"Server '{server_name}' not found."

    cursor.execute("UPDATE servers SET hostname = %s WHERE name = %s", (hostname, server_name))
    conn.commit()
    conn.close()
    return True, f"Hostname for server '{server_name}' updated successfully."


def update_server_memory(server_name, memory_mb):
    """Update a server's memory allocation."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("UPDATE servers SET memory_mb = %s WHERE name = %s", (memory_mb, server_name))
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok
