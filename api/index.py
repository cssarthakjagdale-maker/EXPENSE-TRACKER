import datetime
import json
import math
import os
import re
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# On Vercel Serverless, /tmp is the only writable filesystem
DB_PATH = Path("/tmp") / os.environ.get("DB_NAME", "ledger.db")

ALLOWED_CATEGORIES = {
    "Food",
    "Transport",
    "Housing",
    "Utilities",
    "Entertainment",
    "Shopping",
    "Health",
    "Other",
}

SEED_EXPENSES = [
    ("e1", "2026-07-03", "Housing", "Rent", 1450.0),
    ("e2", "2026-07-05", "Food", "Groceries — Ratnadeep", 62.4),
    ("e3", "2026-07-08", "Transport", "Auto rides", 18.5),
    ("e4", "2026-07-12", "Utilities", "Electricity bill", 74.0),
    ("e5", "2026-07-15", "Entertainment", "Cinema tickets", 22.0),
    ("e6", "2026-08-02", "Housing", "Rent", 1450.0),
    ("e7", "2026-08-06", "Food", "Groceries", 58.1),
    ("e8", "2026-08-10", "Shopping", "New shoes", 89.99),
    ("e9", "2026-08-18", "Health", "Pharmacy", 31.2),
    ("e10", "2026-08-24", "Food", "Dinner out", 44.75),
    ("e11", "2026-09-01", "Housing", "Rent", 1450.0),
    ("e12", "2026-09-02", "Transport", "Fuel", 40.0),
    ("e13", "2026-09-03", "Food", "Groceries", 51.3),
]


def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL
            )
            """
        )
        seeded = conn.execute("SELECT value FROM meta WHERE key = 'seeded'").fetchone()
        if not seeded:
            count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO expenses (id, date, category, description, amount) "
                    "VALUES (?, ?, ?, ?, ?)",
                    SEED_EXPENSES,
                )
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', '1')")
        conn.commit()
    finally:
        conn.close()


class handler(BaseHTTPRequestHandler):
    server_version = "LedgerServerless/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        try:
            init_db()
            conn = get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, date, category, description, amount "
                    "FROM expenses ORDER BY date DESC, id DESC"
                ).fetchall()
                self._send_json(200, [dict(r) for r in rows])
            finally:
                conn.close()
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_POST(self):
        try:
            init_db()
            length_str = self.headers.get("Content-Length", "0")
            length = int(length_str) if str(length_str).isdigit() else 0
            raw = self.rfile.read(length) if length > 0 else b""
            data = json.loads(raw.decode("utf-8")) if raw else {}

            if not isinstance(data, dict):
                self._send_json(400, {"error": "Invalid JSON object."})
                return

            date_val = data.get("date")
            category_val = data.get("category")
            description_val = data.get("description")
            amount_raw = data.get("amount")

            if date_val is None or description_val is None or amount_raw is None:
                self._send_json(400, {"error": "date, description and amount are required."})
                return

            date = str(date_val).strip()
            description = str(description_val).strip()
            category = str(category_val).strip() if category_val is not None else "Other"

            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                self._send_json(400, {"error": "date must be in YYYY-MM-DD format."})
                return
            try:
                datetime.date.fromisoformat(date)
            except ValueError:
                self._send_json(400, {"error": "date must be a valid calendar date."})
                return

            if not description:
                self._send_json(400, {"error": "description cannot be empty."})
                return

            if category not in ALLOWED_CATEGORIES:
                category = "Other"

            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                self._send_json(400, {"error": "amount must be a valid number."})
                return

            if math.isnan(amount) or math.isinf(amount) or amount <= 0:
                self._send_json(400, {"error": "amount must be a positive number."})
                return

            amount = round(amount, 2)
            new_id = "e" + uuid.uuid4().hex[:12]

            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO expenses (id, date, category, description, amount) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_id, date, category, description, amount),
                )
                conn.commit()
            finally:
                conn.close()

            self._send_json(
                201,
                {
                    "id": new_id,
                    "date": date,
                    "category": category,
                    "description": description,
                    "amount": amount,
                },
            )
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_DELETE(self):
        try:
            init_db()
            parsed_path = urlparse(self.path).path
            match = re.search(r"/([^/]+)/?$", parsed_path)
            if not match:
                self._send_json(400, {"error": "Missing expense ID."})
                return

            expense_id = match.group(1)
            conn = get_connection()
            try:
                cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
                conn.commit()
                if cur.rowcount == 0:
                    self._send_json(404, {"error": "Expense not found."})
                else:
                    self._send_json(200, {"deleted": expense_id})
            finally:
                conn.close()
        except Exception as e:
            self._send_json(500, {"error": str(e)})


app = handler
application = handler
