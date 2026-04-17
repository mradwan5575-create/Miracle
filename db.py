"""
SQLite database for tracking products and price history
"""
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class Database:

    def __init__(self, path: str = "data/tracker.db"):
        self.path = path

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT    NOT NULL,
                    asin          TEXT,
                    title         TEXT    DEFAULT 'Unknown',
                    current_price REAL,
                    prev_price    REAL,
                    target_price  REAL,
                    currency      TEXT    DEFAULT 'EGP',
                    available     INTEGER DEFAULT 1,
                    has_alert     INTEGER DEFAULT 0,
                    target_reached INTEGER DEFAULT 0,
                    added_at      TEXT    DEFAULT (datetime('now')),
                    last_checked  TEXT
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    price      REAL,
                    currency   TEXT,
                    recorded_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                );
            """)
        logger.info("✅ Database initialized")

    def add_product(self, url, target=None, title="Unknown",
                    current_price=None, currency="EGP", asin=None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO products (url, asin, title, current_price, target_price, currency)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (url, asin, title, current_price, target, currency)
            )
            pid = cur.lastrowid
            if current_price:
                conn.execute(
                    "INSERT INTO price_history (product_id, price, currency) VALUES (?, ?, ?)",
                    (pid, current_price, currency)
                )
            return pid

    def get_all_products(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_product(self, pid: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            return dict(row) if row else None

    def update_price(self, pid: int, price: float, title: str = None, currency: str = "EGP"):
        with self._conn() as conn:
            old = conn.execute("SELECT current_price FROM products WHERE id=?", (pid,)).fetchone()
            prev = old["current_price"] if old else None
            updates = {
                "prev_price":   prev,
                "current_price": price,
                "last_checked": datetime.now().strftime("%H:%M %d/%m"),
                "available":    1,
            }
            if title:
                updates["title"] = title
            if currency:
                updates["currency"] = currency
            cols = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE products SET {cols} WHERE id=?", (*updates.values(), pid))
            conn.execute(
                "INSERT INTO price_history (product_id, price, currency) VALUES (?, ?, ?)",
                (pid, price, currency)
            )

    def remove_product(self, pid: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM price_history WHERE product_id=?", (pid,))
            conn.execute("DELETE FROM products WHERE id=?", (pid,))

    def get_price_history(self, pid: int, limit: int = 30) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM price_history WHERE product_id=? ORDER BY recorded_at DESC LIMIT ?",
                (pid, limit)
            ).fetchall()
            return [dict(r) for r in rows]
