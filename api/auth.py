"""
User authentication using MongoDB Atlas + bcrypt password hashing.

Collections used:
  users      — { username, password_hash, role, created_at }
  sessions   — handled via Flask-Login + signed cookies (no DB needed)
"""

from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timezone

import bcrypt
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME   = "chainvault"

# ── Connection ────────────────────────────────────────────────────────────────
_client = None
_db     = None


def get_db():
    global _client, _db
    if _db is None:
        if not MONGO_URI:
            raise RuntimeError("MONGO_URI environment variable is not set.")
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _db     = _client[DB_NAME]
        # Unique index on username
        _db.users.create_index("username", unique=True)
    return _db


# ── Password helpers ──────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """bcrypt hash — slow by design to resist brute force."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def _check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Public API ────────────────────────────────────────────────────────────────

def register_user(username: str, password: str, role: str = "user") -> dict:
    """
    Create a new user. Returns the user dict on success.
    Raises ValueError if username already exists or inputs are invalid.
    """
    username = username.strip().lower()

    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if role not in ("user", "admin"):
        raise ValueError("Invalid role.")

    user = {
        "username":      username,
        "password_hash": _hash_password(password),
        "role":          role,
        "created_at":    datetime.now(timezone.utc).isoformat(),
    }

    try:
        get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise ValueError(f"Username '{username}' is already taken.")

    user.pop("password_hash")
    user.pop("_id", None)
    return user


def login_user(username: str, password: str) -> dict | None:
    """
    Verify credentials. Returns user dict (without hash) or None if invalid.
    """
    username = username.strip().lower()
    record   = get_db().users.find_one({"username": username})

    if not record:
        return None
    if not _check_password(password, record["password_hash"]):
        return None

    return {
        "username": record["username"],
        "role":     record["role"],
    }


def get_user(username: str) -> dict | None:
    """Fetch a user by username (without password hash)."""
    record = get_db().users.find_one({"username": username.strip().lower()})
    if not record:
        return None
    return {"username": record["username"], "role": record["role"]}


def user_exists() -> bool:
    """True if at least one user is registered (used to auto-create first admin)."""
    return get_db().users.count_documents({}) > 0
