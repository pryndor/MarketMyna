"""SMTP email notification sender."""

from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger

SMTP_PRESETS = {
    "qq.com": ("smtp.qq.com", 465, True),
    "foxmail.com": ("smtp.qq.com", 465, True),
    "163.com": ("smtp.163.com", 465, True),
    "126.com": ("smtp.126.com", 465, True),
    "gmail.com": ("smtp.gmail.com", 587, False),
    "outlook.com": ("smtp-mail.outlook.com", 587, False),
    "hotmail.com": ("smtp-mail.outlook.com", 587, False),
}



# Attachment file extension -> MIME subtype (application/...).
ATTACHMENT_TYPES = {"pdf": "pdf", "xlsx": "vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

class EmailSender:
    def __init__(self, config, from_address: Optional[str] = None, from_name: Optional[str] = None):
        self._sender = getattr(config, "email_sender", None)
        # Logs in as email_username (or the sender); sends as from_address if given.
        self._login = getattr(config, "email_username", None) or self._sender
        self._from = from_address or self._sender
        self._from_name = from_name or DEFAULT_TITLE
        self._password = getattr(config, "email_password", None)
        self._receivers = getattr(config, "email_receivers", None) or (
            [self._sender] if self._sender else []
        )
        self._smtp_server = getattr(config, "email_smtp_server", None)
        self._smtp_port = getattr(config, "email_smtp_port", None)
        self._smtp_ssl = getattr(config, "email_smtp_ssl", None)

    def is_configured(self) -> bool:
        return bool(self._sender and self._login and self._password and self._receivers)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT,
             html: Optional[str] = None, attachments: Optional[list[tuple[str, bytes]]] = None) -> bool:
        """attachments: (filename, bytes) pairs; the type comes from the extension (PDF, Excel)."""
        if not self.is_configured():
            return False

        subject = title or DEFAULT_TITLE
        domain = self._login.split("@")[-1].lower()
        server_host, port, use_ssl = SMTP_PRESETS.get(domain, (None, None, None))
        server_host = self._smtp_server or server_host or f"smtp.{domain}"
        port = self._smtp_port or port or 465
        use_ssl = self._smtp_ssl if self._smtp_ssl is not None else (use_ssl if use_ssl is not None else True)

        body = MIMEMultipart("alternative")
        body.attach(MIMEText(message, "plain", "utf-8"))
        if html:
            # multipart/alternative: mail apps show the HTML table, others the text.
            body.attach(MIMEText(html, "html", "utf-8"))
        if attachments:
            msg = MIMEMultipart("mixed")
            msg.attach(body)
            for name, data in attachments:
                part = MIMEApplication(data, _subtype=ATTACHMENT_TYPES.get(name.rsplit(".", 1)[-1].lower(), "octet-stream"))
                part.add_header("Content-Disposition", "attachment", filename=name)
                msg.attach(part)
        else:
            msg = body
        msg["Subject"] = subject
        msg["From"] = formataddr((self._from_name, self._from))
        msg["To"] = ", ".join(self._receivers)

        server = None
        try:
            if use_ssl:
                server = smtplib.SMTP_SSL(server_host, port, timeout=timeout)
            else:
                server = smtplib.SMTP(server_host, port, timeout=timeout)
                server.starttls()
            server.login(self._login, self._password)
            server.send_message(msg)
            return True
        except smtplib.SMTPException as exc:
            logger.error("Email send failed: %s", exc)
            return False
        except OSError as exc:
            logger.error("Email send failed: %s", exc)
            return False
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
