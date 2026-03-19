import sqlite3
import os
import secrets

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
            forwarding_secret TEXT
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
    if 'forwarding_secret' not in cols:
        cursor.execute("ALTER TABLE servers ADD COLUMN forwarding_secret TEXT")

    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT
        )
    ''')
    
    # Check if we need to add password column to existing table (migration)
    cursor.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'password' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT")

    # Check if users table is empty
    cursor.execute("SELECT count(*) FROM users")
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', None))
        print("Initialized default 'admin' user with no password.")

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

def generate_forwarding_secret():
    """Generate a random forwarding secret for Velocity modern forwarding."""
    return secrets.token_hex(16)

def update_server_info(name, owner, type, version, jar_path, port=None, hostname=None, container_name=None, forwarding_secret=None):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT id, port, hostname, container_name, forwarding_secret FROM servers WHERE name = ?", (name,))
    data = cursor.fetchone()
    
    if data:
        # If values provided, update them, otherwise keep current
        new_port = port if port is not None else data[1]
        new_hostname = hostname if hostname is not None else data[2]
        new_container = container_name if container_name is not None else data[3]
        new_secret = forwarding_secret if forwarding_secret is not None else data[4]
        cursor.execute('''
            UPDATE servers 
            SET owner = ?, type = ?, version = ?, jar_path = ?, port = ?,
                hostname = ?, container_name = ?, forwarding_secret = ?
            WHERE name = ?
        ''', (owner, type, version, jar_path, new_port, new_hostname, new_container, new_secret, name))
    else:
        # New server. If port not provided, pick next available starting from 25566
        # (25565 is reserved for Velocity proxy)
        if port is None:
            cursor.execute("SELECT max(port) FROM servers")
            max_p = cursor.fetchone()[0]
            port = (max_p + 1) if max_p and max_p >= 25566 else 25566

        # Generate a forwarding secret if not provided
        if forwarding_secret is None:
            forwarding_secret = generate_forwarding_secret()

        # Generate container name if not provided
        if container_name is None:
            container_name = f"mc-{name}"

        cursor.execute('''
            INSERT INTO servers (name, owner, type, version, jar_path, port, hostname, container_name, forwarding_secret)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, owner, type, version, jar_path, port, hostname, container_name, forwarding_secret))
        
    conn.commit()
    conn.close()

def get_server_info(name):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, owner, type, version, jar_path, port, hostname, container_name, forwarding_secret FROM servers WHERE name = ?", (name,))
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
            "forwarding_secret": data[8]
        }
    return None

def get_all_servers():
    """Return a list of all server info dicts."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, owner, type, version, jar_path, port, hostname, container_name, forwarding_secret FROM servers")
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
            "forwarding_secret": data[8]
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

