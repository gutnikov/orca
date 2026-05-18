"""Legacy auth module — mixes three concerns that should live apart."""

import hashlib
import os
import secrets
import time

import requests

OAUTH_CLIENT_ID = "REDACTED"
OAUTH_CLIENT_SECRET = "REDACTED"
OAUTH_TOKEN_URL = "https://example.com/oauth/token"
SESSION_TTL_SECONDS = 3600

_sessions: dict[str, dict] = {}


# --- session handling ---


def create_session(user_id: str) -> str:
    """Mint a new opaque session id and remember it in-process."""
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {"user_id": user_id, "created_at": time.time()}
    return sid


def get_session(sid: str) -> dict | None:
    """Look up a session, expiring it if it's older than the TTL."""
    record = _sessions.get(sid)
    if record is None:
        return None
    if time.time() - record["created_at"] > SESSION_TTL_SECONDS:
        _sessions.pop(sid, None)
        return None
    return record


def destroy_session(sid: str) -> None:
    _sessions.pop(sid, None)


# --- password hashing ---


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Return (hex_salt, hex_hash) using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex(), derived.hex()


def verify_password(password: str, hex_salt: str, expected_hex_hash: str) -> bool:
    _, candidate = hash_password(password, bytes.fromhex(hex_salt))
    return secrets.compare_digest(candidate, expected_hex_hash)


# --- oauth token exchange ---


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Trade an authorization code for an access token from the OAuth provider."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
    }
    response = requests.post(OAUTH_TOKEN_URL, data=payload, timeout=10)
    response.raise_for_status()
    return response.json()
