"""Getting the list in front of you before the order closes.

Three ways out, chosen in config: print it (useful under cron or systemd),
push it to a phone through ntfy, or email it. Each takes the same rendered
text, so adding another channel is one function.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

from .config import NotifyConfig

_LOG = logging.getLogger(__name__)


class NotifyError(Exception):
    """The notification could not be delivered."""


def _send_console(config: NotifyConfig, subject: str, body: str) -> None:
    print(f"\n=== {subject} ===\n{body}\n")


def _send_ntfy(config: NotifyConfig, subject: str, body: str) -> None:
    if not config.ntfy_topic:
        raise NotifyError("notify.ntfy_topic is not set")
    url = f"{config.ntfy_server.rstrip('/')}/{config.ntfy_topic}"
    request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    request.add_header("Title", subject)
    request.add_header("Tags", "shopping_cart")
    if config.ntfy_token:
        request.add_header("Authorization", f"Bearer {config.ntfy_token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise NotifyError(f"ntfy delivery failed: {exc}") from exc


def _send_smtp(config: NotifyConfig, subject: str, body: str) -> None:
    if not (config.smtp_host and config.smtp_to):
        raise NotifyError("notify.smtp_host and notify.smtp_to must both be set")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from or config.smtp_user or config.smtp_to
    message["To"] = config.smtp_to
    message.set_content(body)
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"email delivery failed: {exc}") from exc


CHANNELS = {"console": _send_console, "ntfy": _send_ntfy, "smtp": _send_smtp}


def send(config: NotifyConfig, subject: str, body: str) -> None:
    """Deliver one notification through the configured channel."""
    channel = CHANNELS.get(config.channel)
    if channel is None:
        raise NotifyError(
            f"unknown notify.channel {config.channel!r}; expected one of {', '.join(CHANNELS)}"
        )
    channel(config, subject, body)
    _LOG.info("sent notification via %s", config.channel)
