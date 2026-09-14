"""Notification plumbing, without touching the network."""

from __future__ import annotations

import pytest

from trolley.config import NotifyConfig
from trolley.notify import NotifyError, send


def test_the_console_channel_prints_the_list(capsys) -> None:
    send(NotifyConfig(channel="console"), "Trolley", "Toilet roll\nMilk")
    out = capsys.readouterr().out
    assert "Trolley" in out and "Toilet roll" in out


def test_an_unknown_channel_says_what_is_available() -> None:
    with pytest.raises(NotifyError, match="console"):
        send(NotifyConfig(channel="carrier-pigeon"), "Trolley", "hello")


def test_ntfy_posts_the_body_to_the_topic(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = request.data.decode()
        seen["title"] = request.get_header("Title")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    send(NotifyConfig(channel="ntfy", ntfy_topic="my-shopping"), "Trolley", "Toilet roll")

    assert seen["url"] == "https://ntfy.sh/my-shopping"
    assert seen["body"] == "Toilet roll"
    assert seen["title"] == "Trolley"


def test_a_network_failure_is_reported_not_swallowed(monkeypatch) -> None:
    def boom(request, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(NotifyError, match="ntfy delivery failed"):
        send(NotifyConfig(channel="ntfy", ntfy_topic="t"), "Trolley", "x")


def test_email_needs_somewhere_to_send_to() -> None:
    with pytest.raises(NotifyError, match="smtp_to"):
        send(NotifyConfig(channel="smtp", smtp_host="mail.example.test"), "Trolley", "x")
