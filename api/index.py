import datetime
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import tempfile
import traceback
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Neon / Postgres setup
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL and os.environ.get("DATABASE_URL_UNPOOLED"):
    DATABASE_URL = os.environ.get("DATABASE_URL_UNPOOLED")

# SQLite fallback path for local/offline dev
TMP_DIR = Path(tempfile.gettempdir())
SQLITE_DB = TMP_DIR / os.environ.get("DB_NAME", "ledger.db")

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
    ("2026-07-03", "Housing", "Rent", 1450.0),
    ("2026-07-05", "Food", "Groceries — Ratnadeep", 62.4),
    ("2026-07-08", "Transport", "Auto rides", 18.5),
    ("2026-07-12", "Utilities", "Electricity bill", 74.0),
    ("2026-07-15", "Entertainment", "Cinema tickets", 22.0),
    ("2026-08-02", "Housing", "Rent", 1450.0),
    ("2026-08-06", "Food", "Groceries", 58.1),
    ("2026-08-10", "Shopping", "New shoes", 89.99),
    ("2026-08-18", "Health", "Pharmacy", 31.2),
    ("2026-08-24", "Food", "Dinner out", 44.75),
    ("2026-09-01", "Housing", "Rent", 1450.0),
    ("2026-09-02", "Transport", "Fuel", 40.0),
    ("2026-09-03", "Food", "Groceries", 51.3),
]


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()
    return hashed, salt


class DB:
    """Wrapper that works seamlessly with either Neon Postgres (via pg8000.dbapi) or local SQLite."""

    def __init__(self):
        self.is_pg = bool(DATABASE_URL)
        if self.is_pg:
            import pg8000.dbapi

            parsed = urlparse(DATABASE_URL)
            self.conn = pg8000.dbapi.connect(
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path.lstrip("/"),
                ssl_context=True,
                timeout=15,
            )
        else:
            SQLITE_DB.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(SQLITE_DB), timeout=15.0)
            self.conn.row_factory = sqlite3.Row
            try:
                self.conn.execute("PRAGMA journal_mode=MEMORY")
            except Exception:
                pass

    def run(self, query: str, params: tuple = ()):
        cur = self.conn.cursor()
        try:
            if self.is_pg:
                pg_query = query.replace("?", "%s")
                cur.execute(pg_query, params)
            else:
                cur.execute(query, params)

            self.conn.commit()

            if cur.description:
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            return []
        finally:
            cur.close()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def init_db(db: DB):
    if db.is_pg:
        db.run("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        db.run("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '14 days'
        );
        """)
        db.run("""
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
    else:
        db.run("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT
        );
        """)
        db.run("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT,
            expires_at TEXT
        );
        """)
        db.run("""
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT
        );
        """)


def seed_user_expenses(db: DB, user_id: str):
    count_rows = db.run("SELECT COUNT(*) as c FROM expenses WHERE user_id = ?", (user_id,))
    count = count_rows[0]["c"] if count_rows else 0
    if count == 0:
        for date, cat, desc, amt in SEED_EXPENSES:
            exp_id = "e" + uuid.uuid4().hex[:12]
            db.run(
                "INSERT INTO expenses (id, user_id, date, category, description, amount) VALUES (?, ?, ?, ?, ?, ?)",
                (exp_id, user_id, date, cat, desc, amt),
            )


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload, extra_headers: list = None):
        try:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization"
            )
            if extra_headers:
                for k, v in extra_headers:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            traceback.print_exc()

    def _get_auth_user(self, db: DB):
        # 1. Authorization: Bearer <token>
        auth_hdr = self.headers.get("Authorization", "")
        token = ""
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()

        # 2. Cookie: session=<token>
        if not token:
            cookie_hdr = self.headers.get("Cookie", "")
            for part in cookie_hdr.split(";"):
                part = part.strip()
                if part.startswith("session="):
                    token = part.split("=", 1)[1].strip()

        if not token:
            return None

        rows = db.run(
            """
            SELECT u.id, u.email, u.username
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
            """,
            (token,),
        )
        if rows:
            return rows[0]
        return None

    def _get_request_data(self):
        length_hdr = self.headers.get("Content-Length") or self.headers.get(
            "content-length"
        )
        try:
            length = int(length_hdr) if length_hdr else 0
        except (ValueError, TypeError):
            length = 0

        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return None

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        db = None
        try:
            path = (
                self.headers.get("x-matched-path")
                or self.headers.get("x-forwarded-uri")
                or self.path
                or ""
            ).split("?")[0]

            db = DB()
            init_db(db)

            # Route: GET /api/auth/me
            if path == "/api/auth/me":
                user = self._get_auth_user(db)
                if not user:
                    self._send_json(401, {"error": "Not authenticated."})
                    return
                self._send_json(200, {"user": user})
                return

            # Route: GET /api/expenses (Default for expenses API)
            user = self._get_auth_user(db)
            if not user:
                # If guest access, check if any default user exists, otherwise prompt login
                self._send_json(
                    401, {"error": "Authentication required. Please sign in."}
                )
                return

            rows = db.run(
                """
                SELECT id, date, category, description, amount
                FROM expenses
                WHERE user_id = ?
                ORDER BY date DESC, id DESC
                """,
                (str(user["id"]),),
            )
            self._send_json(200, [dict(r) for r in rows])

        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})
        finally:
            if db:
                db.close()

    def do_POST(self):
        db = None
        try:
            path = (
                self.headers.get("x-matched-path")
                or self.headers.get("x-forwarded-uri")
                or self.path
                or ""
            ).split("?")[0]

            db = DB()
            init_db(db)
            data = self._get_request_data()
            if data is None:
                self._send_json(400, {"error": "Invalid JSON format."})
                return

            # Route: POST /api/auth/signup
            if path == "/api/auth/signup":
                email = str(data.get("email", "")).strip().lower()
                password = str(data.get("password", "")).strip()
                username = str(data.get("username", "")).strip() or email.split("@")[0]

                if not email or "@" not in email:
                    self._send_json(400, {"error": "Valid email address required."})
                    return
                if len(password) < 6:
                    self._send_json(
                        400, {"error": "Password must be at least 6 characters."}
                    )
                    return

                existing = db.run("SELECT id FROM users WHERE email = ?", (email,))
                if existing:
                    self._send_json(
                        400, {"error": "Account with this email already exists."}
                    )
                    return

                pw_hash, salt = hash_password(password)
                user_id = str(uuid.uuid4())

                db.run(
                    "INSERT INTO users (id, email, username, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                    (user_id, email, username, pw_hash, salt),
                )

                # Seed sample expenses for new user
                seed_user_expenses(db, user_id)

                # Create session token
                token = secrets.token_hex(32)
                db.run(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
                    (token, user_id),
                )

                cookie_val = f"session={token}; Path=/; Max-Age=1209600; SameSite=Lax; Secure"
                self._send_json(
                    201,
                    {
                        "token": token,
                        "user": {"id": user_id, "email": email, "username": username},
                    },
                    extra_headers=[("Set-Cookie", cookie_val)],
                )
                return

            # Route: POST /api/auth/login
            elif path == "/api/auth/login":
                email = str(data.get("email", "")).strip().lower()
                password = str(data.get("password", "")).strip()

                if not email or not password:
                    self._send_json(400, {"error": "Email and password required."})
                    return

                users = db.run(
                    "SELECT id, email, username, password_hash, salt FROM users WHERE email = ?",
                    (email,),
                )
                if not users:
                    self._send_json(401, {"error": "Invalid email or password."})
                    return

                u = users[0]
                expected_hash, _ = hash_password(password, u["salt"])
                if not secrets.compare_digest(expected_hash, u["password_hash"]):
                    self._send_json(401, {"error": "Invalid email or password."})
                    return

                token = secrets.token_hex(32)
                db.run(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
                    (token, str(u["id"])),
                )

                cookie_val = f"session={token}; Path=/; Max-Age=1209600; SameSite=Lax; Secure"
                self._send_json(
                    200,
                    {
                        "token": token,
                        "user": {
                            "id": str(u["id"]),
                            "email": u["email"],
                            "username": u["username"],
                        },
                    },
                    extra_headers=[("Set-Cookie", cookie_val)],
                )
                return

            # Route: POST /api/auth/logout
            elif path == "/api/auth/logout":
                cookie_hdr = self.headers.get("Cookie", "")
                token = ""
                for part in cookie_hdr.split(";"):
                    if part.strip().startswith("session="):
                        token = part.strip().split("=", 1)[1].strip()
                if token:
                    db.run("DELETE FROM sessions WHERE token = ?", (token,))

                clear_cookie = (
                    "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0"
                )
                self._send_json(
                    200, {"status": "logged_out"}, extra_headers=[("Set-Cookie", clear_cookie)]
                )
                return

            # Route: POST /api/expenses
            user = self._get_auth_user(db)
            if not user:
                self._send_json(401, {"error": "Authentication required."})
                return

            date_val = data.get("date")
            category_val = data.get("category")
            description_val = data.get("description")
            amount_raw = data.get("amount")

            if date_val is None or description_val is None or amount_raw is None:
                self._send_json(
                    400, {"error": "date, description and amount are required."}
                )
                return

            date = str(date_val).strip()
            description = str(description_val).strip()
            category = (
                str(category_val).strip() if category_val is not None else "Other"
            )

            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                self._send_json(
                    400, {"error": "date must be in YYYY-MM-DD format."}
                )
                return
            try:
                datetime.date.fromisoformat(date)
            except ValueError:
                self._send_json(
                    400, {"error": "date must be a valid calendar date."}
                )
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
                self._send_json(
                    400, {"error": "amount must be a positive number."}
                )
                return

            amount = round(amount, 2)
            new_id = "e" + uuid.uuid4().hex[:12]

            db.run(
                "INSERT INTO expenses (id, user_id, date, category, description, amount) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id, str(user["id"]), date, category, description, amount),
            )

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
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})
        finally:
            if db:
                db.close()

    def do_DELETE(self):
        db = None
        try:
            path = (
                self.headers.get("x-matched-path")
                or self.headers.get("x-forwarded-uri")
                or self.path
                or ""
            ).split("?")[0]

            db = DB()
            init_db(db)
            user = self._get_auth_user(db)
            if not user:
                self._send_json(401, {"error": "Authentication required."})
                return

            match = re.search(r"/([a-zA-Z0-9_\-]+)/?$", path)
            expense_id = match.group(1) if match else None
            if not expense_id or expense_id in ("expenses", "api", "index.py", "index"):
                match = re.search(r"/([a-zA-Z0-9_\-]+)/?$", self.path.split("?")[0])
                expense_id = match.group(1) if match else None

            if not expense_id or expense_id in ("expenses", "api", "index.py", "index"):
                self._send_json(400, {"error": "Missing expense ID."})
                return

            # Only delete if user owns this expense
            rows = db.run(
                "SELECT id FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, str(user["id"])),
            )
            if not rows:
                self._send_json(404, {"error": "Expense not found."})
                return

            db.run(
                "DELETE FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, str(user["id"])),
            )
            self._send_json(200, {"deleted": expense_id})

        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})
        finally:
            if db:
                db.close()

    def log_message(self, format, *args):
        pass
