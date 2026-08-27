import hashlib
import os
import time
from typing import Any


ORACLE_SESSION_TTL = int(os.getenv("ORACLE_SESSION_TTL_SECONDS", "1800"))
_ORACLE_SESSIONS: dict[str, dict[str, Any]] = {}


def save_oracle_session(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    key = _key(user_id)
    expires_at = int(time.time()) + ORACLE_SESSION_TTL

    _ORACLE_SESSIONS[key] = {
        "config": {
            "base_url": config["base_url"].rstrip("/"),
            "username": config["username"],
            "password": config["password"],
            "auth_mode": config.get("auth_mode", "basic"),
            "rest_version": config.get("rest_version") or os.getenv("ORACLE_REST_VERSION", "11.13.18.05"),
        },
        "expiresAt": expires_at,
    }

    return {"expiresIn": ORACLE_SESSION_TTL, "expiresAt": expires_at}


def get_oracle_session(user_id: str) -> dict[str, Any]:
    key = _key(user_id)
    session = _ORACLE_SESSIONS.get(key)

    if not session:
        raise RuntimeError("Oracle credentials are not connected. Please connect Oracle first.")

    if int(time.time()) >= int(session["expiresAt"]):
        _ORACLE_SESSIONS.pop(key, None)
        raise RuntimeError("Oracle session expired. Please reconnect Oracle.")

    return session["config"]


def clear_oracle_session(user_id: str) -> None:
    _ORACLE_SESSIONS.pop(_key(user_id), None)


def has_oracle_session(user_id: str) -> bool:
    try:
        get_oracle_session(user_id)
        return True
    except Exception:
        return False


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()