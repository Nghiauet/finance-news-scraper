"""JWT-based authentication for the admin portal."""

import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

load_dotenv()

_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", 24))

_JWT_SECRET = os.environ.get("JWT_SECRET") or hashlib.sha256(
    (_PASSWORD + "scrape-news-salt").encode()
).hexdigest()


def login(username: str, password: str) -> str | None:
    """Validate credentials and return a JWT token, or None on failure."""
    if not _PASSWORD:
        return None
    if username == _USERNAME and password == _PASSWORD:
        return create_token(username)
    return None


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    """Decode and validate a JWT. Raises on failure."""
    return jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])


def require_admin(request: Request) -> str:
    """FastAPI dependency — extracts and validates Bearer token.
    Returns the username on success, raises HTTPException(401) on failure."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[7:]
    try:
        payload = verify_token(token)
        return payload["sub"]
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        raise HTTPException(status_code=401, detail=str(e))
