import secrets
import json
import sqlite3
import threading
import time
from typing import Dict, List
from fastapi import HTTPException, status
from app.config import BASE_DIR

# In-memory token store
TOKEN_STORE: Dict[str, dict] = {}
TOKEN_DB_PATH = str(BASE_DIR / "backend.db")
_TOKEN_LOCK = threading.Lock()


def _token_conn(timeout: float = 8.0) -> sqlite3.Connection:
    conn = sqlite3.connect(TOKEN_DB_PATH, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def _ensure_token_table():
    with _token_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def generate_token() -> str:
    return secrets.token_hex(32)


def store_token(token: str, payload: dict):
    TOKEN_STORE[token] = payload
    with _TOKEN_LOCK:
        _ensure_token_table()
        # best-effort persistence: keep login healthy even under transient sqlite writer contention
        attempts = 0
        while attempts < 5:
            try:
                with _token_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO auth_tokens(token, payload) VALUES (?, ?)",
                        (token, json.dumps(payload))
                    )
                    conn.commit()
                    return
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                attempts += 1
                time.sleep(0.08 * attempts)
            except Exception:
                attempts += 1
                time.sleep(0.08 * attempts)
        return


def get_token_payload(token: str):
    in_memory = TOKEN_STORE.get(token)
    if in_memory is not None:
        return in_memory

    with _TOKEN_LOCK:
        _ensure_token_table()
        with _token_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM auth_tokens WHERE token = ?",
                (token,)
            ).fetchone()

    if not row:
        return None

    payload = json.loads(row[0])
    TOKEN_STORE[token] = payload
    return payload


def require_roles(allowed_roles: List[str]):
    def checker(user_payload: dict):
        role = user_payload.get("role")
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized for this role"
            )
        return user_payload
    return checker
