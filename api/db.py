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
