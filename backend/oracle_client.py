import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_REST_VERSION = os.getenv("ORACLE_REST_VERSION", "11.13.18.05")


class OracleConfigError(RuntimeError):
    pass


class OracleClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auth_mode: str | None = None,
        rest_version: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ORACLE_BASE_URL", "")).rstrip("/")
        self.auth_mode = (auth_mode or os.getenv("ORACLE_AUTH_MODE", "basic")).lower()
        self.username = username if username is not None else os.getenv("ORACLE_USERNAME", "")
        self.password = password if password is not None else os.getenv("ORACLE_PASSWORD", "")
        self.rest_version = rest_version or DEFAULT_REST_VERSION
        self.timeout = int(os.getenv("ORACLE_TIMEOUT_SECONDS", "30"))
        self._token_cache: dict[str, Any] = {"token": None, "expires_at": 0}
        self._validate()

    def _validate(self) -> None:
        missing = []

        if not self.base_url or "your-oracle-fusion-host" in self.base_url:
            missing.append("ORACLE_BASE_URL/base_url")

        if self.auth_mode == "basic":
            if not self.username:
                missing.append("ORACLE_USERNAME/username")
            if not self.password:
                missing.append("ORACLE_PASSWORD/password")
        elif self.auth_mode == "oauth":
            for key in ("ORACLE_CLIENT_ID", "ORACLE_CLIENT_SECRET"):
                if not os.getenv(key):
                    missing.append(key)
        else:
            missing.append("auth_mode must be basic or oauth")

        if missing:
            raise OracleConfigError("Missing or invalid Oracle config: " + ", ".join(missing))

    def _token(self) -> str:
        now = time.time()
        if self._token_cache["token"] and now < self._token_cache["expires_at"] - 30:
            return str(self._token_cache["token"])

        token_url = os.getenv("ORACLE_TOKEN_URL") or f"{self.base_url}/oauth/token"
        client_id = os.getenv("ORACLE_CLIENT_ID", "")
        client_secret = os.getenv("ORACLE_CLIENT_SECRET", "")
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        response = requests.post(
            token_url,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"grant_type": "client_credentials", "scope": "urn:opc:resource:consumer::all"},
            timeout=self.timeout,
        )

        self._raise_for_status(response)
        data = response.json()

        self._token_cache = {
            "token": data["access_token"],
            "expires_at": now + int(data.get("expires_in", 3600)),
        }

        return str(data["access_token"])

    def _request_kwargs(self) -> dict[str, Any]:
        headers = {"Accept": "application/json"}

        if self.auth_mode == "basic":
            return {
                "auth": HTTPBasicAuth(self.username, self.password),
                "headers": headers,
            }

        headers["Authorization"] = f"Bearer {self._token()}"
        return {"headers": headers}

    def resource_url(self, resource_path: str) -> str:
        clean_path = resource_path.strip("/")
        return f"{self.base_url}/fscmRestApi/resources/{self.rest_version}/{clean_path}"

    def get(self, resource_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(
            self.resource_url(resource_path),
            params=params or {},
            timeout=self.timeout,
            **self._request_kwargs(),
        )
        self._raise_for_status(response)
        return response.json()

    def paginate(
        self,
        resource_path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int,
        max_pages: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        base_params = dict(params or {})

        for _ in range(max_pages):
            data = self.get(resource_path, {**base_params, "limit": limit, "offset": offset})
            page_rows = data.get("items", [])

            if not isinstance(page_rows, list):
                raise RuntimeError(f"Unexpected Oracle payload: items is {type(page_rows).__name__}")

            rows.extend(page_rows)

            if not data.get("hasMore"):
                break

            offset += int(data.get("limit") or limit)

        return rows

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return

        body = response.text[:1000]
        body_lower = body.lower()

        if response.status_code == 401:
            raise RuntimeError("401 Unauthorized. Check Oracle URL, username, password, or REST access.")

        if response.status_code == 403:
            raise RuntimeError("403 Forbidden. User lacks privileges for this REST resource.")

        if response.status_code == 503:
            if "planned outage" in body_lower or "scheduled maintenance" in body_lower:
                raise RuntimeError(
                    "Oracle Fusion is currently under scheduled maintenance. "
                    "Please try again after the Oracle pod is restored."
                )
            raise RuntimeError("Oracle Fusion is temporarily unavailable with HTTP 503.")

        raise RuntimeError(f"Oracle request failed with HTTP {response.status_code}. Body: {body}")


def oracle_status() -> dict[str, Any]:
    try:
        client = OracleClient()
        return {
            "connected": True,
            "baseUrl": client.base_url,
            "authMode": client.auth_mode,
            "message": "Oracle configuration is present.",
        }
    except Exception as exc:
        return {"connected": False, "message": str(exc)}


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")