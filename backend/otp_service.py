import hashlib
import os
import random
import secrets
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from .cache_service import cache_delete, cache_get_json, cache_key, cache_set_json
except ImportError:
    from cache_service import cache_delete, cache_get_json, cache_key, cache_set_json


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def request_signup_otp(email: str) -> dict[str, Any]:
    email = _clean_email(email)
    otp = f"{random.randint(100000, 999999)}"
    salt = secrets.token_hex(16)
    ttl = int(os.getenv("OTP_TTL_SECONDS", "60"))

    key = _otp_key(email)
    payload = {
        "email": email,
        "salt": salt,
        "otpHash": _hash_otp(otp, salt),
        "attempts": 0,
        "expiresAt": int(time.time()) + ttl,
    }

    cache_set_json(key, payload, ttl)
    _send_otp_email(email, otp)

    return {
        "email": email,
        "expiresIn": ttl,
        "message": "OTP sent to your email.",
    }


def verify_signup_otp(email: str, otp: str) -> dict[str, Any]:
    email = _clean_email(email)
    key = _otp_key(email)
    record = cache_get_json(key)

    if not record:
        raise RuntimeError("OTP expired. Please request a new OTP.")

    max_attempts = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
    attempts = int(record.get("attempts", 0)) + 1

    if attempts > max_attempts:
        cache_delete(key)
        raise RuntimeError("Too many incorrect OTP attempts. Please request a new OTP.")

    expected = record.get("otpHash", "")
    actual = _hash_otp(str(otp).strip(), record.get("salt", ""))

    if expected != actual:
        record["attempts"] = attempts
        remaining_ttl = max(1, int(record.get("expiresAt", 0)) - int(time.time()))
        cache_set_json(key, record, remaining_ttl)
        raise RuntimeError("Invalid OTP.")

    cache_delete(key)
    return {"email": email, "verified": True}


def _clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        raise RuntimeError("Enter a valid email address.")
    return email


def _otp_key(email: str) -> str:
    return cache_key("signup-otp", {"email": email})


def _hash_otp(otp: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{otp}".encode("utf-8")).hexdigest()


def _send_otp_email(to_email: str, otp: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_user
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not smtp_host or not smtp_user or not smtp_password or not smtp_from:
        raise RuntimeError("SMTP is not configured. Add Gmail SMTP values in .env.")

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = to_email
    message["Subject"] = "Your Oracle PO Chatbot verification code"
    message.set_content(
        f"Your Oracle PO Chatbot verification code is: {otp}\n\n"
        "This code expires in 1 minute.\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)