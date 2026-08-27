import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def upstash_request(command_parts: list[str]) -> dict:
    base_url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    if not base_url or not token:
        raise RuntimeError(
            "Missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN in .env"
        )

    encoded_parts = [quote(str(part), safe="") for part in command_parts]
    url = f"{base_url}/{'/'.join(encoded_parts)}"

    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if response.status_code >= 400:
        raise RuntimeError(
            f"Upstash request failed: HTTP {response.status_code}. Body: {data}"
        )

    return data


def main() -> int:
    base_url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    print("Redis cache probe")
    print(f"REST URL: {base_url}")
    print(f"Token present: {bool(token)}")
    print()

    print("PING")
    ping = upstash_request(["PING"])
    print(json.dumps(ping, indent=2))
    print()

    key = f"oracle-po-chatbot:test:{int(time.time())}"
    value = {
        "message": "Redis cache is working",
        "page": 1,
        "pageSize": 20,
        "source": "test_redis_cache.py",
    }

    print("SET test JSON value")
    set_result = upstash_request(["SET", key, json.dumps(value), "EX", "60"])
    print(json.dumps(set_result, indent=2))
    print()

    print("GET test JSON value")
    get_result = upstash_request(["GET", key])
    print(json.dumps(get_result, indent=2))
    print()

    cached_value = json.loads(get_result.get("result") or "{}")
    if cached_value != value:
        raise RuntimeError("Redis value mismatch. SET worked, but GET returned different data.")

    print("DEL test key")
    del_result = upstash_request(["DEL", key])
    print(json.dumps(del_result, indent=2))
    print()

    print("SUCCESS: Upstash Redis REST cache is working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())