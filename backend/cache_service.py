import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("oracle_po_chatbot.cache")


def cache_status() -> dict[str, Any]:
    return {
        "enabled": _enabled(),
        "provider": "upstash-rest" if _enabled() else "none",
    }


def ttl_seconds(env_name: str, default: int) -> int:
    try:
        return int(os.getenv(env_name, str(default)))
    except ValueError:
        return default


def cache_key(namespace: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"oracle-po-chatbot:{namespace}:{digest}"


def cache_get_json(key: str) -> Any | None:
    if not _enabled():
        return None

    try:
        data = _command(["GET", key])
        raw = data.get("result")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis cache GET failed for %s: %s", key, exc)
        return None


def cache_set_json(key: str, value: Any, ttl: int) -> None:
    if not _enabled():
        return

    try:
        raw = json.dumps(value, default=str, separators=(",", ":"))
        _command(["SET", key, raw, "EX", ttl])
    except Exception as exc:
        logger.warning("Redis cache SET failed for %s: %s", key, exc)

def cache_delete(key: str) -> None:
    if not _enabled():
        return

    try:
        _command(["DEL", key])
    except Exception as exc:
        logger.warning("Redis cache DEL failed for %s: %s", key, exc)

def _enabled() -> bool:
    return bool(
        os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
        and os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
    )


def _command(parts: list[Any]) -> dict[str, Any]:
    base_url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    response = requests.post(
        base_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(parts),
        timeout=20,
    )

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if response.status_code >= 400 or "error" in data:
        raise RuntimeError(f"HTTP {response.status_code}: {data}")

    return data