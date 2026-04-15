import sqlite3
import os

DB_PATH = "data/data.db"

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # Check for column migrations
    cursor.execute("PRAGMA table_info(servers)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'port' not in cols:
        cursor.execute("ALTER TABLE servers ADD COLUMN port INTEGER DEFAULT 25565")
    if 'hostname' not in cols:
        cursor.execute("ALTER TABLE servers ADD COLUMN hostname TEXT")
    if 'container_name' not in cols:
        cursor.execute("ALTER TABLE servers ADD COLUMN container_name TEXT")
    if 'memory_mb' not in cols:
        cursor.execute("ALTER TABLE servers ADD COLUMN memory_mb INTEGER DEFAULT 1024")
    # Drop legacy column: forwarding_secret was used for Velocity modern forwarding.
    # Infrared does not require it. Requires SQLite 3.35+ (July 2021).
    if 'forwarding_secret' in cols:
        try:
            cursor.execute("ALTER TABLE servers DROP COLUMN forwarding_secret")
        except sqlite3.OperationalError as e:
            print(f"[DB] Warning: could not drop 'forwarding_secret' column: {e}. "
                  "Requires SQLite 3.35+. Column will be left in place.")

    # Migrate existing servers to use standard port 25565
    # (each container has its own IP, so no port conflicts)
    cursor.execute("UPDATE servers SET port = 25565 WHERE port != 25565")


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT,
            memory_limit INTEGER DEFAULT 4096
        )
    ''')
    
    # Check if we need to add password and memory columns to existing table (migration)
    cursor.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'password' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT")
    if 'memory_limit' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN memory_limit INTEGER DEFAULT 4096")

    # Check if users table is empty
    cursor.execute("SELECT count(*) FROM users")
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute("INSERT INTO users (username, password, memory_limit) VALUES (?, ?, ?)", ('admin', None, 8192))
        print("Initialized default 'admin' user.")
        
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at DATETIME
        )
    ''')

    conn.commit()
    conn.close()

def set_user_password(username, password):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    
    if user:
        cursor.execute("UPDATE users SET password = ? WHERE username = ?", (password, username))
        conn.commit()
        conn.close()
        return True
    else:
        conn.close()
        return False

def get_user_info(username):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, memory_limit FROM users WHERE username = ?", (username,))
    data = cursor.fetchone()
    conn.close()
    if data:
        return {"username": data[0], "memory_limit": data[1]}
    return None

def update_user_memory(username, limit_mb):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET memory_limit = ? WHERE username = ?", (limit_mb, username))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def verify_user_password(username, password):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if exists
    cursor.execute("SELECT id, port, hostname, container_name, memory_mb FROM servers WHERE name = ?", (name,))
    data = cursor.fetchone()

    if data:
        # If values provided, update them, otherwise keep current
        new_port = port if port is not None else data[1]
        new_hostname = hostname if hostname is not None else data[2]
        new_container = container_name if container_name is not None else data[3]
        new_memory = memory_mb if memory_mb is not None else data[4]
        cursor.execute('''
            UPDATE servers
            SET owner = ?, type = ?, version = ?, jar_path = ?, port = ?,
                hostname = ?, container_name = ?, memory_mb = ?
            WHERE name = ?
        ''', (owner, type, version, jar_path, new_port, new_hostname, new_container, new_memory, name))
    else:
        if port is None:
            port = 25565

        # Generate container name if not provided
        if container_name is None:
            container_name = f"mc-{name}"

        if memory_mb is None:
            memory_mb = 1024

        cursor.execute('''
            INSERT INTO servers (name, owner, type, version, jar_path, port, hostname, container_name, memory_mb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, owner, type, version, jar_path, port, hostname, container_name, memory_mb))

    conn.commit()
    conn.close()

def get_server_info(name):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, owner, type, version, jar_path, port, hostname, container_name, memory_mb FROM servers WHERE name = ?", (name,))
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
            "memory_mb": data[8]
        }
    return None

def get_all_servers():
    """Return a list of all server info dicts."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, owner, type, version, jar_path, port, hostname, container_name, memory_mb FROM servers")
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
            "memory_mb": data[8]
        })
    return servers

def delete_server(name):
    """Delete a server from the database."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM servers WHERE name = ?", (name,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_user(username):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_user(username):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = ?", (username,))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

def get_users():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def set_server_owner(server_name, owner_name):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM servers WHERE name = ?", (server_name,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return False, "Server not found."
    
    cursor.execute("SELECT id FROM users WHERE username = ?", (owner_name,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, f"User '{owner_name}' not found."

    cursor.execute("UPDATE servers SET owner = ? WHERE name = ?", (owner_name, server_name))
    conn.commit()
    conn.close()
    return True, f"Owner of server '{server_name}' updated to '{owner_name}'."


def update_server_hostname(server_name, hostname):
    """Update a server's hostname."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM servers WHERE name = ?", (server_name,))
    if not cursor.fetchone():
        conn.close()
        return False, f"Server '{server_name}' not found."
        
    cursor.execute("UPDATE servers SET hostname = ? WHERE name = ?", (hostname, server_name))
    conn.commit()
    conn.close()
    return True, f"Hostname for server '{server_name}' updated successfully."

def update_server_memory(server_name, memory_mb):
    """Update a server's memory allocation."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("UPDATE servers SET memory_mb = ? WHERE name = ?", (memory_mb, server_name))
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok

