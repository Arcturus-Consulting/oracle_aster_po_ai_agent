import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def firebase_web_config() -> dict[str, str]:
    return {
        "apiKey": os.getenv("FIREBASE_WEB_API_KEY", ""),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
        "projectId": os.getenv("FIREBASE_PROJECT_ID", ""),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", ""),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
        "appId": os.getenv("FIREBASE_APP_ID", ""),
    }


def create_email_password_user(email: str, password: str) -> dict[str, Any]:
    _validate_firebase_config()
    _validate_password(password)

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={os.getenv('FIREBASE_WEB_API_KEY')}"
    return _identity_toolkit_post(
        url,
        {
            "email": email.strip().lower(),
            "password": password,
            "returnSecureToken": True,
        },
    )


def sign_in_email_password_user(email: str, password: str) -> dict[str, Any]:
    _validate_firebase_config()

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={os.getenv('FIREBASE_WEB_API_KEY')}"
    return _identity_toolkit_post(
        url,
        {
            "email": email.strip().lower(),
            "password": password,
            "returnSecureToken": True,
        },
    )


def verify_firebase_id_token(id_token: str) -> dict[str, Any]:
    _validate_firebase_config()

    if not id_token:
        raise RuntimeError("Missing Firebase token.")

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={os.getenv('FIREBASE_WEB_API_KEY')}"
    response = requests.post(url, json={"idToken": id_token}, timeout=30)

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if response.status_code >= 400:
        message = data.get("error", {}).get("message", "Firebase token verification failed.")
        raise RuntimeError(_friendly_firebase_error(message))

    users = data.get("users") or []
    if not users:
        raise RuntimeError("Firebase token verification failed.")

    user = users[0]
    providers = user.get("providerUserInfo") or []

    return {
        "uid": user.get("localId"),
        "email": user.get("email", ""),
        "emailVerified": bool(user.get("emailVerified")),
        "provider": providers[0].get("providerId", "") if providers else "",
        "claims": user,
    }


def _identity_toolkit_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, json=payload, timeout=30)

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if response.status_code >= 400:
        message = data.get("error", {}).get("message", "Firebase authentication failed.")
        raise RuntimeError(_friendly_firebase_error(message))

    return {
        "idToken": data["idToken"],
        "refreshToken": data.get("refreshToken"),
        "uid": data.get("localId"),
        "email": data.get("email"),
        "expiresIn": int(data.get("expiresIn", "3600")),
    }


def _validate_firebase_config() -> None:
    missing = [
        key
        for key in ("FIREBASE_WEB_API_KEY", "FIREBASE_PROJECT_ID")
        if not os.getenv(key)
    ]
    if missing:
        raise RuntimeError("Missing Firebase config: " + ", ".join(missing))


def _validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise RuntimeError("Password must be at least 8 characters.")


def _friendly_firebase_error(message: str) -> str:
    mapping = {
        "EMAIL_EXISTS": "This email is already registered. Please sign in.",
        "EMAIL_NOT_FOUND": "No account exists for this email.",
        "INVALID_PASSWORD": "Incorrect password.",
        "INVALID_LOGIN_CREDENTIALS": "Invalid email or password.",
        "INVALID_ID_TOKEN": "Your login token expired or is invalid. Please sign in again.",
        "USER_DISABLED": "This user account is disabled.",
    }
    return mapping.get(message, message.replace("_", " ").title())