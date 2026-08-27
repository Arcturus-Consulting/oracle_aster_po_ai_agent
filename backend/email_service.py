import os
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

import requests


MAIL_TEMPLATE = """Hello {supplier_name},

This is a follow-up for overdue purchase order {order_number}.

Order details:
- Order Number: {order_number}
- Line/Schedule: {line_schedule}
- Item: {description}
- Due Date: {due_date}
- Delay: {late_days} day(s)
- Current Status: {status}

Please confirm the expected delivery date and share any shipment/update details.

Regards,
Procurement Team
"""


def build_supplier_followup_email(row: dict) -> dict:
    to_email = row.get("supplierEmail") or row.get("SupplierEmailAddress") or ""
    order_number = row.get("orderNumber") or "the purchase order"

    subject = f"Follow-up on overdue purchase order {order_number}"
    body = MAIL_TEMPLATE.format(
        supplier_name=row.get("supplier") or "Supplier",
        order_number=order_number,
        line_schedule=row.get("lineSchedule") or "-",
        description=row.get("description") or "-",
        due_date=row.get("dueDate") or "-",
        late_days=row.get("lateDays") if row.get("lateDays") is not None else "-",
        status=row.get("status") or "Open",
    )

    mailto = ""
    if to_email:
        mailto = f"mailto:{to_email}?subject={quote(subject)}&body={quote(body)}"

    return {
        "to": to_email,
        "subject": subject,
        "body": body,
        "mailto": mailto,
    }


def send_supplier_email(row: dict) -> dict:
    draft = build_supplier_followup_email(row)

    if not draft["to"]:
        return {
            "sent": False,
            "reason": "No supplier email is available for this order.",
            "draft": draft,
        }

    provider = os.getenv("EMAIL_PROVIDER", "smtp").strip().lower()

    if provider == "resend":
        return _send_with_resend(draft)

    return _send_with_smtp(draft)


def _send_with_resend(draft: dict) -> dict:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("RESEND_FROM", "").strip()

    if not api_key or not sender:
        return {
            "sent": False,
            "reason": "Resend is not configured. Add RESEND_API_KEY and RESEND_FROM.",
            "draft": draft,
        }

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": sender,
            "to": [draft["to"]],
            "subject": draft["subject"],
            "text": draft["body"],
        },
        timeout=30,
    )

    if response.status_code >= 400:
        return {
            "sent": False,
            "reason": f"Resend email failed: {response.text[:500]}",
            "draft": draft,
        }

    return {
        "sent": True,
        "provider": "resend",
        "to": draft["to"],
        "subject": draft["subject"],
        "draft": draft,
    }


def _send_with_smtp(draft: dict) -> dict:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_user
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not smtp_host or not smtp_user or not smtp_password or not smtp_from:
        return {
            "sent": False,
            "reason": "SMTP is not fully configured in .env.",
            "draft": draft,
        }

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = draft["to"]
    message["Subject"] = draft["subject"]
    message.set_content(draft["body"])

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)

    return {
        "sent": True,
        "provider": "smtp",
        "to": draft["to"],
        "subject": draft["subject"],
        "draft": draft,
    }