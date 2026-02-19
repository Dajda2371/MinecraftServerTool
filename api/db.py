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
            jar_path TEXT
        )
    ''')
    
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

def update_server_info(name, owner, type, version, jar_path):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT id FROM servers WHERE name = ?", (name,))
    data = cursor.fetchone()
    
    if data:
        cursor.execute('''
            UPDATE servers 
            SET owner = ?, type = ?, version = ?, jar_path = ?
            WHERE name = ?
        ''', (owner, type, version, jar_path, name))
    else:
        cursor.execute('''
            INSERT INTO servers (name, owner, type, version, jar_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, owner, type, version, jar_path))
        
    conn.commit()
    conn.close()

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
    
    # Check if user exists? The schema says owner is TEXT DEFAULT 'admin', not a foreign key.
    # However, for consistency, we should check if the user exists in users table ONLY IF the user model is strictly enforced.
    # But current schema for servers.owner is just TEXT. 
    # Let's enforce that the owner must be a valid user if users table is being used.
    
    cursor.execute("SELECT id FROM users WHERE username = ?", (owner_name,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, f"User '{owner_name}' not found."

    cursor.execute("UPDATE servers SET owner = ? WHERE name = ?", (owner_name, server_name))
    conn.commit()
    conn.close()
    return True, f"Owner of server '{server_name}' updated to '{owner_name}'."

