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
