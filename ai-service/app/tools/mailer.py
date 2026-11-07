"""Email over SMTP with STARTTLS, set by SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD and
MAIL_FROM (default SMTP_USER); for example Gmail with an app password. Nothing is faked: without
SMTP_HOST sending fails."""

import asyncio
import hashlib
import os
import smtplib
from email.message import EmailMessage

from app.core.tools import ToolError


async def send(to: str, subject: str, body: str, key: str) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        raise ToolError("mail is not configured", "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and MAIL_FROM for ai-service.")
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM") or os.getenv("SMTP_USER", "")
    msg["To"] = to
    msg["Subject"] = subject
    # The same approved action always carries the same id, so a second copy shows as a duplicate
    msg["Message-ID"] = f"<{hashlib.sha256(key.encode()).hexdigest()[:32]}@nexus.local>"
    msg.set_content(body)
    try:
        await asyncio.to_thread(_deliver, host, msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise ToolError(f"sending failed: {type(exc).__name__}: {exc}",
                        "Check whether the customer got the email before sending it again by hand.") from exc


def _deliver(host: str, msg: EmailMessage) -> None:
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        if user := os.getenv("SMTP_USER"):
            smtp.login(user, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
