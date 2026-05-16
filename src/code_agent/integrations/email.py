from __future__ import annotations

import json
import smtplib
import ssl
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    source: str = "agent"


class EmailIntegration:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or Path.home() / ".agent-email.json")
        self.config: dict = {}
        if self.config_path.exists():
            try:
                self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                pass

    def is_configured(self) -> bool:
        return bool(self.config.get("smtp_server") and self.config.get("email"))

    def configure(self, smtp_server: str, port: int, email: str, password: str, use_tls: bool = True) -> None:
        self.config = {
            "smtp_server": smtp_server,
            "port": port,
            "email": email,
            "password": password,
            "use_tls": use_tls,
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def send(self, message: EmailMessage) -> bool:
        if not self.is_configured():
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.config["email"]
            msg["To"] = message.to
            msg["Subject"] = message.subject
            if message.cc:
                msg["Cc"] = ", ".join(message.cc)

            msg.attach(MIMEText(message.body, "plain"))

            all_recipients = [message.to] + message.cc + message.bcc

            context = ssl.create_default_context()
            with smtplib.SMTP(self.config["smtp_server"], self.config["port"]) as server:
                if self.config.get("use_tls", True):
                    server.starttls(context=context)
                server.login(self.config["email"], self.config["password"])
                server.sendmail(self.config["email"], all_recipients, msg.as_string())

            return True
        except Exception:
            return False

    def inbox(self) -> list[dict]:
        return [{"note": "Email inbox requires IMAP configuration. Use a dedicated email client for full inbox management."}]
