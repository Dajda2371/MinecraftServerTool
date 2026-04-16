import secrets
import datetime
import api.db

def create_session(username):
    token = secrets.token_urlsafe(32)
    api.db.init_db()
    conn = api.db._connect()
    cursor = conn.cursor()
    # Expire in 24 hours
    expires_at = datetime.datetime.now() + datetime.timedelta(hours=24)
    cursor.execute("INSERT INTO sessions (token, username, expires_at) VALUES (%s, %s, %s)",
                   (token, username, expires_at))
    conn.commit()
    conn.close()
    return token

def get_session_user(token):
    if not token:
        return None
    api.db.init_db()
    conn = api.db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT username, expires_at FROM sessions WHERE token = %s", (token,))
    data = cursor.fetchone()
    conn.close()
    if data:
        # psycopg2 returns datetime directly for TIMESTAMP columns.
        expires_at = data[1]
        if datetime.datetime.now() < expires_at:
            return data[0]
        else:
            delete_session(token)
    return None

def delete_session(token):
    if not token:
        return
    api.db.init_db()
    conn = api.db._connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
    conn.commit()
    conn.close()

def parse_cookies(headers):
    cookies = {}
    cookie_header = headers.get('Cookie')
    if cookie_header:
        for chunk in cookie_header.split(';'):
            if '=' in chunk:
                name, val = chunk.split('=', 1)
                cookies[name.strip()] = val.strip()
    return cookies
