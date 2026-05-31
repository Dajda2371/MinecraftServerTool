import os
from datetime import datetime, timezone
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS console_commands (
            id          SERIAL PRIMARY KEY,
            server_name TEXT NOT NULL,
            username    TEXT NOT NULL,
            command     TEXT NOT NULL,
            sent_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_console_commands_server "
        "ON console_commands (server_name, sent_at)"
    )

    # Firewall Rules Table and migration
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS firewall_rules (
            id SERIAL PRIMARY KEY,
            server_name TEXT NOT NULL REFERENCES servers(name) ON DELETE CASCADE,
            protocol TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            internal_port INTEGER NOT NULL,
            external_port INTEGER NOT NULL,
            label TEXT
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firewall_rules_server ON firewall_rules(server_name)")

    conn.commit()
    conn.close()


def log_console_command(server_name: str, username: str, command: str) -> None:
    """Persist a command typed by *username* for *server_name*."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO console_commands (server_name, username, command) "
        "VALUES (%s, %s, %s)",
        (server_name, username, command),
    )
    conn.commit()
    conn.close()


def get_console_commands(server_name: str, limit: int = 400):
    """
    Return the last *limit* commands sent to *server_name* as a list of dicts:
        {"command": str, "username": str, "sent_at": datetime}
    Ordered oldest-first so they can be merged with latest.log.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT command, username, sent_at
        FROM (
            SELECT command, username, sent_at
            FROM console_commands
            WHERE server_name = %s
            ORDER BY sent_at DESC
            LIMIT %s
        ) sub
        ORDER BY sent_at ASC
        """,
        (server_name, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"command": r[0], "username": r[1], "sent_at": r[2]}
        for r in rows
    ]


def delete_console_commands(server_name: str) -> None:
    """Remove all stored commands for a server (called on server delete)."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM console_commands WHERE server_name = %s", (server_name,))
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


# ---------------------------------------------------------------------------
# Firewall Rules CRUD & Helpers
# ---------------------------------------------------------------------------

def get_server_firewall_rules(server_name: str):
    """Return a list of all firewall rules for a server."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, server_name, protocol, enabled, internal_port, external_port, label "
        "FROM firewall_rules WHERE server_name = %s ORDER BY id ASC",
        (server_name,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    rules = []
    for r in rows:
        rules.append({
            "id": r[0],
            "server_name": r[1],
            "protocol": r[2],
            "enabled": r[3],
            "internal_port": r[4],
            "external_port": r[5],
            "label": r[6] or ""
        })
    return rules


def get_firewall_rule(rule_id: int):
    """Retrieve a single firewall rule by ID."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, server_name, protocol, enabled, internal_port, external_port, label "
        "FROM firewall_rules WHERE id = %s",
        (rule_id,)
    )
    r = cursor.fetchone()
    conn.close()
    if r:
        return {
            "id": r[0],
            "server_name": r[1],
            "protocol": r[2],
            "enabled": r[3],
            "internal_port": r[4],
            "external_port": r[5],
            "label": r[6] or ""
        }
    return None


def check_external_port_collision(protocol: str, external_port: int, exclude_id: int = None) -> bool:
    """
    Check if a rule with the same protocol and external port already exists.
    Optionally excludes a specific rule ID (useful for edits).
    """
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    if exclude_id is not None:
        cursor.execute(
            "SELECT COUNT(*) FROM firewall_rules "
            "WHERE protocol = %s AND external_port = %s AND id != %s",
            (protocol, external_port, exclude_id)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM firewall_rules "
            "WHERE protocol = %s AND external_port = %s",
            (protocol, external_port)
        )
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def get_next_available_udp_port() -> int:
    """
    Find the lowest available UDP external port in range 23000-23999.
    Excludes any ports already registered across all servers.
    """
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT external_port FROM firewall_rules WHERE protocol = 'UDP'")
    used_ports = {row[0] for row in cursor.fetchall()}
    conn.close()
    
    for port in range(23000, 24000):
        if port not in used_ports:
            return port
    raise ValueError("All UDP ports in range 23000-23999 are exhausted.")


def add_firewall_rule(server_name: str, protocol: str, enabled: bool, internal_port: int, external_port: int, label: str) -> int:
    """Add a new firewall rule to the database and return its ID."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO firewall_rules (server_name, protocol, enabled, internal_port, external_port, label) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (server_name, protocol.upper(), enabled, internal_port, external_port, label)
    )
    rule_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return rule_id


def update_firewall_rule(rule_id: int, enabled: bool, internal_port: int, label: str, external_port: int = None) -> bool:
    """
    Update an existing firewall rule.
    If external_port is provided (only allowed/used for TCP rules), it updates it as well.
    """
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    
    if external_port is not None:
        cursor.execute(
            "UPDATE firewall_rules "
            "SET enabled = %s, internal_port = %s, label = %s, external_port = %s "
            "WHERE id = %s",
            (enabled, internal_port, label, external_port, rule_id)
        )
    else:
        cursor.execute(
            "UPDATE firewall_rules "
            "SET enabled = %s, internal_port = %s, label = %s "
            "WHERE id = %s",
            (enabled, internal_port, label, rule_id)
        )
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def delete_firewall_rule(rule_id: int) -> bool:
    """Delete a firewall rule by ID."""
    init_db()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM firewall_rules WHERE id = %s", (rule_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_server_port_from_properties(server_name: str) -> int:
    """
    Read the server-port property from the server's properties file,
    updating the DB 'servers' table 'port' column to keep it in sync,
    and defaulting to the database value or 25565.
    """
    import os
    server_local_path = os.path.abspath(os.path.join("data", "servers", server_name))
    props_path = os.path.join(server_local_path, "server.properties")
    port = None
    if os.path.exists(props_path):
        try:
            with open(props_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        if key.strip() == "server-port":
                            port = int(value.strip())
                            break
        except Exception as e:
            print(f"[get_server_port_from_properties Error] {e}")

    conn = _connect()
    cursor = conn.cursor()
    
    # Fallback if not found in properties file
    if port is None:
        cursor.execute("SELECT port FROM servers WHERE name = %s", (server_name,))
        row = cursor.fetchone()
        port = row[0] if (row and row[0]) else 25565
    else:
        # Keep the DB in sync with properties file
        cursor.execute("UPDATE servers SET port = %s WHERE name = %s AND port != %s", (port, server_name, port))
        conn.commit()
        
    conn.close()
    return port

