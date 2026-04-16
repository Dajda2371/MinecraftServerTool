"""
One-shot migrator: SQLite data.db  ->  PostgreSQL (via api.db)

Run inside the mc-tool container so it has the same POSTGRES_* env and the
mc-data volume mounted at /app/data:

    docker compose run --rm mc-tool python scripts/migrate_sqlite_to_postgres.py

Behaviour:
  * Reads data/data.db (or $SQLITE_PATH) read-only.
  * Ensures the target schema exists by calling api.db.init_db().
  * Copies servers, users, and sessions. ON CONFLICT DO NOTHING / UPDATE
    makes the script safe to re-run.
  * Prints a one-line summary. Exit code 0 on success, 1 on any error.
"""

from __future__ import annotations

import os
import sqlite3
import sys

# Import lazily so the failure mode when psycopg2 is missing is obvious.
import api.db


SQLITE_PATH = os.environ.get("SQLITE_PATH", "data/data.db")


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_servers(src: sqlite3.Connection, dst) -> int:
    """Copy rows from sqlite.servers into postgres.servers.

    Skips rows whose `name` already exists in Postgres so the script is
    idempotent.
    """
    cols = _sqlite_columns(src, "servers")
    if not cols:
        return 0
    # Use a stable column order we know the Postgres schema has.
    select_cols = [
        "name", "owner", "type", "version", "jar_path",
        "port", "hostname", "container_name", "memory_mb",
    ]
    # Older sqlite DBs might be missing some columns — fill with NULL.
    select_sql_cols = ", ".join(c if c in cols else "NULL AS " + c for c in select_cols)
    rows = src.execute(f"SELECT {select_sql_cols} FROM servers").fetchall()
    if not rows:
        return 0

    cur = dst.cursor()
    migrated = 0
    for row in rows:
        cur.execute(
            """
            INSERT INTO servers
                (name, owner, type, version, jar_path, port, hostname, container_name, memory_mb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            """,
            tuple(row),
        )
        migrated += cur.rowcount
    dst.commit()
    return migrated


def _migrate_users(src: sqlite3.Connection, dst) -> int:
    """Copy rows from sqlite.users into postgres.users.

    On conflict on `username`, we update `password` and `memory_limit` to
    the SQLite values — the SQLite DB is the authoritative source during a
    one-shot migration.
    """
    cols = _sqlite_columns(src, "users")
    if not cols:
        return 0
    select_cols = ["username", "password", "memory_limit"]
    select_sql_cols = ", ".join(c if c in cols else "NULL AS " + c for c in select_cols)
    rows = src.execute(f"SELECT {select_sql_cols} FROM users").fetchall()
    if not rows:
        return 0

    cur = dst.cursor()
    migrated = 0
    for row in rows:
        cur.execute(
            """
            INSERT INTO users (username, password, memory_limit)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE
                SET password = EXCLUDED.password,
                    memory_limit = EXCLUDED.memory_limit
            """,
            tuple(row),
        )
        migrated += cur.rowcount
    dst.commit()
    return migrated


def _migrate_sessions(src: sqlite3.Connection, dst) -> int:
    """Copy rows from sqlite.sessions into postgres.sessions.

    SQLite stored expires_at as ISO text; PostgreSQL expects a TIMESTAMP.
    psycopg2 accepts an ISO string as a TIMESTAMP literal, so we can pass
    the raw value through.
    """
    cols = _sqlite_columns(src, "sessions")
    if not cols:
        return 0
    rows = src.execute(
        "SELECT token, username, expires_at FROM sessions"
    ).fetchall()
    if not rows:
        return 0

    cur = dst.cursor()
    migrated = 0
    for row in rows:
        cur.execute(
            """
            INSERT INTO sessions (token, username, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token) DO NOTHING
            """,
            tuple(row),
        )
        migrated += cur.rowcount
    dst.commit()
    return migrated


def main() -> int:
    if not os.path.exists(SQLITE_PATH):
        print(f"[migrate] No SQLite database at {SQLITE_PATH}; nothing to do.")
        return 0

    print(f"[migrate] Source:      {SQLITE_PATH}")
    print(f"[migrate] Destination: postgres://{api.db.DB_USER}@{api.db.DB_HOST}:{api.db.DB_PORT}/{api.db.DB_NAME}")

    print("[migrate] Ensuring Postgres schema...")
    api.db.init_db()

    # Open SQLite read-only via the URI form so we can't accidentally
    # mutate the legacy DB.
    src = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    try:
        dst = api.db._connect()
        try:
            n_servers = _migrate_servers(src, dst)
            n_users = _migrate_users(src, dst)
            n_sessions = _migrate_sessions(src, dst)
        finally:
            dst.close()
    finally:
        src.close()

    print(
        f"[migrate] Done. migrated {n_servers} servers, "
        f"{n_users} users, {n_sessions} sessions."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — one-shot CLI, surface everything
        print(f"[migrate] FAILED: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
