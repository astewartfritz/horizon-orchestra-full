"""Email notifications package."""
from orchestra.code_agent.notifications.email import (
    EmailNotification,
    init_db,
    send_email,
    send_invite_email,
    send_compliance_alert,
    send_billing_summary,
    send_weekly_digest,
    send_breach_alert,
    list_notifications,
)

__all__ = [
    "EmailNotification",
    "init_db",
    "send_email",
    "send_invite_email",
    "send_compliance_alert",
    "send_billing_summary",
    "send_weekly_digest",
    "send_breach_alert",
    "list_notifications",
]
