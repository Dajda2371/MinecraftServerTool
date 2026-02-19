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
            username TEXT NOT NULL UNIQUE
        )
    ''')
    conn.commit()
    conn.close()

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

def init_server_owners():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(server_id) REFERENCES servers(id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(server_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()

def add_server_owner(server_name, username):
    init_server_owners()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM servers WHERE name = ?", (server_name,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return False, "Server not found."
    server_id = server[0]

    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, "User not found."
    user_id = user[0]

    try:
        cursor.execute("INSERT INTO server_owners (server_id, user_id) VALUES (?, ?)", (server_id, user_id))
        conn.commit()
        conn.close()
        return True, "Owner added."
    except sqlite3.IntegrityError:
        conn.close()
        return False, "User is already an owner."

def remove_server_owner(server_name, username):
    init_server_owners()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM servers WHERE name = ?", (server_name,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return False, "Server not found."
    server_id = server[0]

    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, "User not found."
    user_id = user[0]

    cursor.execute("DELETE FROM server_owners WHERE server_id = ? AND user_id = ?", (server_id, user_id))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    
    if changes > 0:
        return True, "Owner removed."
    else:
        return False, "User was not an owner."

def get_server_owners(server_name):
    init_server_owners()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM servers WHERE name = ?", (server_name,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return []
    
    server_id = server[0]
    cursor.execute('''
        SELECT u.username FROM users u
        JOIN server_owners so ON u.id = so.user_id
        WHERE so.server_id = ?
    ''', (server_id,))
    
    owners = [row[0] for row in cursor.fetchall()]
    conn.close()
    return owners
