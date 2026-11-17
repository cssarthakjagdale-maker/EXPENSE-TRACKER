"""
Schema migration script for Neon Postgres.
Uses DATABASE_URL_UNPOOLED (direct connection) as required for migrations.
"""
import os
import sys
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k not in os.environ:
                    os.environ[k] = v

db_url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL_UNPOOLED not found in .env")
    sys.exit(1)

try:
    import pg8000.native as pg
except ImportError:
    print("Installing pg8000...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pg8000"])
    import pg8000.native as pg

from urllib.parse import urlparse

parsed = urlparse(db_url)

conn = pg.Connection(
    user=parsed.username,
    password=parsed.password,
    host=parsed.hostname,
    port=parsed.port or 5432,
    database=parsed.path.lstrip("/"),
    ssl_context=True,
)

print("Connected to Neon Postgres. Running migrations...")

conn.run("""
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
""")
print("✓ users table")

conn.run("""
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);
""")
print("✓ sessions table")

conn.run("""
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
print("✓ expenses table")

conn.run("CREATE INDEX IF NOT EXISTS idx_expenses_user_id ON expenses(user_id);")
conn.run("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
conn.run("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")
print("✓ indexes")

conn.close()
print("\n✅ Migration complete! Tables: users, sessions, expenses")
