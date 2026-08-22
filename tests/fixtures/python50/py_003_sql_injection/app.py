import sqlite3
def find_user(conn: sqlite3.Connection, name: str):
    query = f"SELECT id, name FROM users WHERE name = '{name}'"
    return conn.execute(query).fetchall()
