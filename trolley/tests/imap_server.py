"""A very small IMAP server, so the client can be tested over a real socket.

The fake in `fake_imap.py` stands in for imaplib itself, which is fast but
leaves imaplib's own command building and literal parsing untested. This is the
other half: a real socket, real IMAP wire format, real imaplib.
"""

from __future__ import annotations

import re
import socket
import threading


class TinyIMAP:
    """Enough of IMAP4rev1 for the commands Trolley sends, and nothing more."""

    def __init__(self, messages: dict[int, bytes], uidvalidity: str = "4242") -> None:
        self.messages = dict(messages)
        self.uidvalidity = uidvalidity
        self.folders = {"INBOX"}
        self.logins: list[tuple[str, str]] = []
        self.commands: list[str] = []
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "TinyIMAP":
        self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(client,), daemon=True).start()

    def _session(self, client: socket.socket) -> None:
        stream = client.makefile("rwb")
        stream.write(b"* OK [CAPABILITY IMAP4rev1 UIDPLUS] TinyIMAP ready\r\n")
        stream.flush()
        try:
            while True:
                line = stream.readline()
                if not line:
                    return
                if self._handle(stream, line.decode("utf-8", "replace").strip()):
                    return
        except (OSError, ValueError):
            return
        finally:
            try:
                stream.close()
                client.close()
            except OSError:
                pass

    @staticmethod
    def _unquote(value: str) -> str:
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return value

    def _handle(self, stream, line: str) -> bool:
        tag, _, rest = line.partition(" ")
        name, _, args = rest.partition(" ")
        name = name.upper()
        self.commands.append(rest)

        def send(*lines: bytes) -> None:
            for item in lines:
                stream.write(item + b"\r\n")
            stream.flush()

        if name == "CAPABILITY":
            send(b"* CAPABILITY IMAP4rev1 UIDPLUS", f"{tag} OK done".encode())
        elif name == "LOGIN":
            user, _, password = args.partition(" ")
            user, password = self._unquote(user), self._unquote(password)
            self.logins.append((user, password))
            if password == "wrong":
                send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials".encode())
            else:
                send(f"{tag} OK LOGIN completed".encode())
        elif name in ("SELECT", "EXAMINE"):
            folder = self._unquote(args)
            if folder not in self.folders:
                send(f"{tag} NO [NONEXISTENT] Unknown Mailbox".encode())
            else:
                send(
                    f"* {len(self.messages)} EXISTS".encode(),
                    f"* OK [UIDVALIDITY {self.uidvalidity}] UIDs valid".encode(),
                    f"{tag} OK [READ-ONLY] {name} completed".encode(),
                )
        elif name == "STATUS":
            folder = self._unquote(args.rsplit("(", 1)[0])
            send(
                f'* STATUS "{folder}" (UIDVALIDITY {self.uidvalidity})'.encode(),
                f"{tag} OK STATUS completed".encode(),
            )
        elif name == "UID":
            self._uid(stream, tag, args, send)
        elif name == "LOGOUT":
            send(b"* BYE logging out", f"{tag} OK LOGOUT completed".encode())
            return True
        else:
            send(f"{tag} BAD unknown command {name}".encode())
        return False

    def _uid(self, stream, tag: str, args: str, send) -> None:
        sub, _, rest = args.partition(" ")
        sub = sub.upper()
        if sub == "SEARCH":
            uids = sorted(self.messages)
            window = re.search(r"UID (\d+):\*", rest)
            if window:
                uids = [uid for uid in uids if uid >= int(window.group(1))]
            send(
                ("* SEARCH " + " ".join(str(uid) for uid in uids)).strip().encode(),
                f"{tag} OK SEARCH completed".encode(),
            )
        elif sub == "FETCH":
            wanted, _, _ = rest.partition(" ")
            raw = self.messages.get(int(wanted))
            if raw is None:
                send(f"{tag} OK FETCH completed".encode())
                return
            stream.write(f"* 1 FETCH (UID {wanted} RFC822 {{{len(raw)}}}\r\n".encode())
            stream.write(raw)
            stream.write(b")\r\n")
            stream.write(f"{tag} OK FETCH completed\r\n".encode())
            stream.flush()
        else:
            send(f"{tag} BAD unknown UID command".encode())
