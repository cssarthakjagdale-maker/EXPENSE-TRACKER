import sys
from pathlib import Path

# Add project root directory to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server import LedgerRequestHandler, init_db

# Initialize database schema in writable /tmp directory on Vercel
init_db()


# Top-level entrypoint classes and variables for Vercel Serverless runtime
class handler(LedgerRequestHandler):
    pass


app = handler
application = handler
