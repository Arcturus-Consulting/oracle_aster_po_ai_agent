import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_SESSION_TTL = int(os.getenv("APP_SESSION_TTL_SECONDS", "1800"))
PBKDF2_ITERATIONS = 210_000


def signup_user(email: str, password: str) -> dict[str, Any]:
    email = _clean_email(email)
    _validate_password(password)

    key = _user_key(email)
    if _redis_get_json(key):
        raise RuntimeError("This user already exists. Please sign in.")

    salt = secrets.token_hex(16)
    user = {
        "email": email,
        "salt": salt,
        "passwordHash": _hash_password(password, salt),
        "iterations": PBKDF2_ITERATIONS,
        "createdAt": int(time.time()),
    }

    _redis_set_json(key, user)
    return create_session(email)


def login_user(email: str, password: str) -> dict[str, Any]:
    email = _clean_email(email)
    user = _redis_get_json(_user_key(email))

    if not user:
        raise RuntimeError("Invalid email or password.")

    expected = user.get("passwordHash", "")
    actual = _hash_password(password, user.get("salt", ""))

    if not hmac.compare_digest(expected, actual):
        raise RuntimeError("Invalid email or password.")

    return create_session(email)


def create_session(email: str) -> dict[str, Any]:
    token = secrets.token_urlsafe(36)
    session = {
        "email": email,
        "createdAt": int(time.time()),
        "expiresAt": int(time.time()) + APP_SESSION_TTL,
    }

    _redis_set_json(_session_key(token), session, ttl=APP_SESSION_TTL)

    return {
        "token": token,
        "email": email,
        "expiresIn": APP_SESSION_TTL,
    }


def get_session(token: str) -> dict[str, Any]:
    if not token:
        raise RuntimeError("Please sign in first.")

    session = _redis_get_json(_session_key(token))
    if not session:
        raise RuntimeError("Your login session expired. Please sign in again.")

    return session


def logout_user(token: str) -> None:
    if token:
        _redis_command(["DEL", _session_key(token)])


def _clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        raise RuntimeError("Enter a valid email address.")
    return email


def _validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise RuntimeError("Password must be at least 8 characters.")


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()


def _safe_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_key(email: str) -> str:
    return f"oracle-po-chatbot:user:{email}"


def _session_key(token: str) -> str:
    return f"oracle-po-chatbot:app-session:{_safe_token_hash(token)}"


def _redis_get_json(key: str) -> Any | None:
    data = _redis_command(["GET", key])
    raw = data.get("result")
    return json.loads(raw) if raw else None


def _redis_set_json(key: str, value: Any, ttl: int | None = None) -> None:
    payload = json.dumps(value, separators=(",", ":"), default=str)
    command = ["SET", key, payload]
    if ttl:
        command += ["EX", ttl]
    _redis_command(command)


def _redis_command(parts: list[Any]) -> dict[str, Any]:
    base_url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    if not base_url or not token:
        raise RuntimeError("Upstash Redis is not configured.")

    response = requests.post(
        base_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(parts),
        timeout=20,
    )

    data = response.json()
    if response.status_code >= 400 or data.get("error"):
        raise RuntimeError(f"Redis error: {data}")

    return data