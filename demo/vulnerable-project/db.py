import sqlite3


def get_user_by_email(email):
    conn = sqlite3.connect("app.db")
    query = "SELECT * FROM users WHERE email='" + email + "'"
    return conn.execute(query).fetchone()


def delete_order(order_id):
    conn = sqlite3.connect("app.db")
    conn.execute(f"DELETE FROM orders WHERE id={order_id}")
