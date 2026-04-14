import sqlite3
import os

DB_PATH = os.environ.get('DB_PATH', 'prices.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id     TEXT    NOT NULL,
        url         TEXT    NOT NULL,
        name        TEXT,
        platform    TEXT,
        current_price REAL,
        target_price  REAL,
        last_checked  TEXT,
        added_at      TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS price_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        price      REAL,
        checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    )''')
    conn.commit()
    conn.close()

def add_product(chat_id, url, name, platform, price, target_price=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO products (chat_id, url, name, platform, current_price, target_price) VALUES (?,?,?,?,?,?)',
        (chat_id, url, name, platform, price, target_price)
    )
    pid = c.lastrowid
    c.execute('INSERT INTO price_history (product_id, price) VALUES (?,?)', (pid, price))
    conn.commit()
    conn.close()
    return pid

def get_products(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM products WHERE chat_id=? ORDER BY added_at DESC', (chat_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_products():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM products')
    rows = c.fetchall()
    conn.close()
    return rows

def update_price(product_id, price):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'UPDATE products SET current_price=?, last_checked=CURRENT_TIMESTAMP WHERE id=?',
        (price, product_id)
    )
    c.execute('INSERT INTO price_history (product_id, price) VALUES (?,?)', (product_id, price))
    conn.commit()
    conn.close()

def remove_product(product_id, chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM price_history WHERE product_id=?', (product_id,))
    c.execute('DELETE FROM products WHERE id=? AND chat_id=?', (product_id, chat_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_price_history(product_id, limit=8):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT price, checked_at FROM price_history WHERE product_id=? ORDER BY checked_at DESC LIMIT ?',
        (product_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_product_by_id(product_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM products WHERE id=?', (product_id,))
    row = c.fetchone()
    conn.close()
    return row
