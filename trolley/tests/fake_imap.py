"""A stand-in IMAP server, enough of one to exercise the mailbox reader."""

from __future__ import annotations

import re
from datetime import date, timedelta


def build_email(subject: str, body: str, sent: date | None = None) -> bytes:
    sent = sent or date(2026, 9, 14)
    return (
        f"From: Tesco <noreply@tesco.test>\r\n"
        f"To: shopper@example.test\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {sent:%a, %d %b %Y} 09:00:00 +0100\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"{body}"
    ).encode()


def receipt_html(order_ref: str, delivered_on: date, lines: list[tuple[int, str, str]]) -> str:
    rows = "".join(
        f"<tr><td>{qty}</td><td>{name}</td><td>&pound;{price}</td></tr>"
        for qty, name, price in lines
    )
    return (
        "<html><body>"
        f"<p>Order number: {order_ref}</p>"
        f"<p>Delivery date: {delivered_on:%d %B %Y}</p>"
        f"<table>{rows}"
        "<tr><td>1</td><td>Delivery charge</td><td>&pound;4.50</td></tr>"
        "<tr><td></td><td>Total</td><td>&pound;61.45</td></tr>"
        "</table></body></html>"
    )


class FakeIMAP:
    """Implements only the handful of commands Mailbox actually issues."""

    def __init__(
        self,
        messages: dict[int, bytes] | None = None,
        uidvalidity: str = "1000",
        fail_login: bool = False,
        fail_select: bool = False,
        expect_password: str | None = None,
        folders: tuple[str, ...] = (),
        web_login_alert: bool = False,
    ) -> None:
        self.messages = dict(messages or {})
        self.uidvalidity = uidvalidity
        self.fail_login = fail_login
        self.fail_select = fail_select
        #: When set, only this exact password is accepted, which is how the
        #: Gmail app-password handling is checked.
        self.expect_password = expect_password
        #: When set, only these folder names can be selected.
        self.folders = folders
        self.web_login_alert = web_login_alert
        self.password_seen: str | None = None
        self.logged_in = False
        self.selected: str | None = None
        self.readonly: bool | None = None
        self.flagged: list[int] = []
        self.searches: list[str] = []
        self.logouts = 0

    # ----- the IMAP surface Mailbox uses -----

    def login(self, user: str, password: str):
        self.password_seen = password
        if self.web_login_alert:
            raise Exception(
                "b'[ALERT] Please log in via your web browser: "
                "https://support.google.com/mail/accounts/answer/78754 (Failure)'"
            )
        if self.fail_login or (
            self.expect_password is not None and password != self.expect_password
        ):
            raise Exception("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")
        self.logged_in = True
        return "OK", [b"LOGIN completed"]

    def select(self, mailbox: str, readonly: bool = True):
        if self.fail_select:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        if self.folders and mailbox not in self.folders:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox (Failure)"]
        self.selected, self.readonly = mailbox, readonly
        return "OK", [str(len(self.messages)).encode()]

    def status(self, mailbox: str, names: str):
        return "OK", [f'"{mailbox}" (UIDVALIDITY {self.uidvalidity})'.encode()]

    def uid(self, command: str, *args):
        command = command.upper()
        if command == "SEARCH":
            return self._search(args[-1])
        if command == "FETCH":
            return self._fetch(args[0])
        if command == "STORE":
            self.flagged.extend(int(uid) for uid in str(args[0]).split(","))
            return "OK", [b""]
        raise AssertionError(f"unexpected IMAP command {command}")

    def logout(self):
        self.logouts += 1
        return "BYE", [b""]

    # ----- query handling -----

    def _search(self, query: str):
        self.searches.append(query)
        uids = sorted(self.messages)
        window = re.search(r"UID (\d+):\*", query)
        if window:
            uids = [uid for uid in uids if uid >= int(window.group(1))]
        return "OK", [" ".join(str(uid) for uid in uids).encode()]

    def _fetch(self, uid: str):
        raw = self.messages.get(int(uid))
        if raw is None:
            return "NO", [None]
        return "OK", [(f"{uid} (RFC822 {{{len(raw)}}}".encode(), raw)]
