import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    from .agent import run_chat
    from .cache_service import cache_status
    from .email_service import send_supplier_email
    from .firebase_auth_service import (
        create_email_password_user,
        firebase_web_config,
        sign_in_email_password_user,
        verify_firebase_id_token,
    )
    from .oracle_client import OracleClient, oracle_status
    from .oracle_session import clear_oracle_session, get_oracle_session, has_oracle_session, save_oracle_session
    from .otp_service import request_signup_otp, verify_signup_otp
    from .po_tools import get_overdue_open_po_schedules
except ImportError:
    from agent import run_chat
    from cache_service import cache_status
    from email_service import send_supplier_email
    from firebase_auth_service import (
        create_email_password_user,
        firebase_web_config,
        sign_in_email_password_user,
        verify_firebase_id_token,
    )
    from oracle_client import OracleClient, oracle_status
    from oracle_session import clear_oracle_session, get_oracle_session, has_oracle_session, save_oracle_session
    from otp_service import request_signup_otp, verify_signup_otp
    from po_tools import get_overdue_open_po_schedules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "index.html"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oracle_po_chatbot")

app = FastAPI(title="Oracle Fusion PO Chatbot", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class EmailRequest(BaseModel):
    row: dict[str, Any]


class EmailPasswordRequest(BaseModel):
    email: str
    password: str


class OtpRequest(BaseModel):
    email: str


class OtpSignupRequest(BaseModel):
    email: str
    password: str
    otp: str


class OracleConnectRequest(BaseModel):
    baseUrl: str
    username: str
    password: str
    authMode: str = "basic"
    restVersion: str = "11.13.18.05"


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Please sign in first.")
    return authorization.split(" ", 1)[1].strip()


def require_firebase_user(token: str = Depends(bearer_token)) -> dict[str, Any]:
    try:
        return verify_firebase_id_token(token)
    except Exception as exc:
        raise HTTPException(401, str(exc))


def require_oracle_config(user: dict[str, Any] = Depends(require_firebase_user)) -> dict[str, Any]:
    try:
        return get_oracle_session(user["uid"])
    except Exception as exc:
        raise HTTPException(401, str(exc))


@app.get("/")
def frontend():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(404, "Frontend file not found.")
    return FileResponse(
        FRONTEND_INDEX,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/firebase-config")
def firebase_config():
    return {"success": True, "config": firebase_web_config()}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Oracle Fusion PO Chatbot",
        "oracle": oracle_status(),
        "cache": cache_status(),
    }


@app.post("/api/auth/request-otp")
def request_otp(req: OtpRequest):
    try:
        return {"success": True, **request_signup_otp(req.email)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/auth/verify-otp-signup")
def verify_otp_signup(req: OtpSignupRequest):
    try:
        verify_signup_otp(req.email, req.otp)
        return {"success": True, **create_email_password_user(req.email, req.password)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/auth/login")
def login(req: EmailPasswordRequest):
    try:
        return {"success": True, **sign_in_email_password_user(req.email, req.password)}
    except Exception as exc:
        raise HTTPException(401, str(exc))


@app.post("/api/auth/logout")
def logout(user: dict[str, Any] = Depends(require_firebase_user)):
    clear_oracle_session(user["uid"])
    return {"success": True}


@app.get("/api/session")
def session(user: dict[str, Any] = Depends(require_firebase_user)):
    return {
        "success": True,
        "email": user.get("email", ""),
        "uid": user.get("uid", ""),
        "oracleConnected": has_oracle_session(user["uid"]),
    }


@app.post("/api/oracle/connect")
def oracle_connect(req: OracleConnectRequest, user: dict[str, Any] = Depends(require_firebase_user)):
    config = {
        "base_url": req.baseUrl,
        "username": req.username,
        "password": req.password,
        "auth_mode": req.authMode,
        "rest_version": req.restVersion,
    }

    try:
        client = OracleClient(**config)
        client.get("purchaseOrderSchedules", {"limit": 1, "onlyData": "true"})
        session_data = save_oracle_session(user["uid"], config)
        return {
            "success": True,
            "message": "Oracle credentials verified.",
            "oracleSession": session_data,
        }
    except Exception as exc:
        logger.exception("Oracle credential verification failed")
        raise HTTPException(401, str(exc))


@app.post("/api/oracle/disconnect")
def oracle_disconnect(user: dict[str, Any] = Depends(require_firebase_user)):
    clear_oracle_session(user["uid"])
    return {"success": True}


@app.post("/api/chat")
async def chat(req: ChatRequest, oracle_config: dict[str, Any] = Depends(require_oracle_config)):
    messages = [m.model_dump() for m in req.history]
    messages.append({"role": "user", "content": req.message})

    try:
        result = await run_chat(messages, oracle_config=oracle_config)
        return {"success": True, **result}
    except Exception as exc:
        logger.exception("Chat request failed")
        raise HTTPException(500, str(exc))


@app.post("/api/send-mail")
def send_mail(req: EmailRequest, _: dict[str, Any] = Depends(require_firebase_user)):
    try:
        return {"success": True, **send_supplier_email(req.row)}
    except Exception as exc:
        logger.exception("Email send failed")
        raise HTTPException(500, str(exc))


@app.get("/api/overdue-schedules")
def overdue_schedules(
    page: int = 1,
    page_size: int = 20,
    sort_order: str = "desc",
    destination_type: str = "",
    oracle_config: dict[str, Any] = Depends(require_oracle_config),
):
    try:
        return {
            "success": True,
            **get_overdue_open_po_schedules(
                page=page,
                page_size=page_size,
                sort_order=sort_order,
                destination_type=destination_type,
                oracle_config=oracle_config,
            ),
        }
    except Exception as exc:
        logger.exception("Overdue schedule page failed")
        raise HTTPException(500, str(exc))


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8000")),
        reload=True,
    )