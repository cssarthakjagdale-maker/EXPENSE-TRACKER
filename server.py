"""
The Household Ledger - backend server.

A tiny, dependency-free HTTP server (uses only the Python standard library)
that serves the ledger's static front end and persists expense entries in a
SQLite database (ledger.db) instead of an in-memory JavaScript array.

Run with:  python server.py
Then open: http://localhost:8000
"""

import datetime
import json
import math
import os
import re
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

def load_dotenv(env_path: Path):
    """Simple, dependency-free .env file loader."""
    if not env_path.is_file():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'").strip()
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
DB_NAME = os.environ.get("DB_NAME", "ledger.db")

if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp") / DB_NAME
elif os.environ.get("DB_PATH"):
    DB_PATH = Path(os.environ["DB_PATH"])
else:
    DB_PATH = BASE_DIR / DB_NAME

INDEX_FILE = BASE_DIR / "index.html"

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

# Seed data - mirrors the sample entries that used to live directly in the
# front-end JavaScript. Only inserted the first time the database is created.
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
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
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


class LedgerRequestHandler(BaseHTTPRequestHandler):
    server_version = "LedgerHTTP/1.1"

    # ---------- helpers ----------
    def _send_json(self, status, payload):
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            return {}
        try:
            length = int(content_length_str)
            if length < 0:
                raise ValueError("Negative Content-Length header.")
        except ValueError:
            raise ValueError("Invalid Content-Length header.")

        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Request body must be valid UTF-8.")

        data = json.loads(decoded)
        if not isinstance(data, dict):
            raise ValueError("Request JSON body must be an object.")
        return data

    # ---------- routes ----------
    def do_HEAD(self):
        parsed_path = urlparse(self.path).path
        if parsed_path in ("/", "/index.html"):
            try:
                data = INDEX_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path).path
        if parsed_path in ("/", "/index.html"):
            self._send_file(INDEX_FILE, "text/html; charset=utf-8")
        elif parsed_path == "/api/expenses":
            conn = get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, date, category, description, amount "
                    "FROM expenses ORDER BY date DESC, id DESC"
                ).fetchall()
                self._send_json(200, [dict(r) for r in rows])
            finally:
                conn.close()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path).path
        if parsed_path != "/api/expenses":
            self.send_response(404)
            self.end_headers()
            return

        try:
            data = self._read_json_body()
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(400, {"error": str(e)})
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

        # Validate date format (YYYY-MM-DD) and calendar validity
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
        if len(description) > 255:
            self._send_json(400, {"error": "description cannot exceed 255 characters."})
            return

        if category not in ALLOWED_CATEGORIES:
            category = "Other"

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "amount must be a valid number."})
            return

        if math.isnan(amount) or math.isinf(amount) or amount <= 0:
            self._send_json(400, {"error": "amount must be a positive, finite number."})
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
            {"id": new_id, "date": date, "category": category, "description": description, "amount": amount},
        )

    def do_DELETE(self):
        parsed_path = urlparse(self.path).path
        match = re.match(r"^/api/expenses/([^/]+)/?$", parsed_path)
        if not match:
            self.send_response(404)
            self.end_headers()
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

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), LedgerRequestHandler)
    print(f"The Household Ledger is running: http://{HOST}:{PORT}")
    print(f"SQLite database file: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
