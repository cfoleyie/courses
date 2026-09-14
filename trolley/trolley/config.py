"""Configuration, read from a TOML file with sensible defaults for everything.

Secrets (SMTP password, ntfy token) come from the environment rather than the
file, so the config can live in version control next to the rest of the setup.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .slots import SlotSpec, weekday_number

DEFAULT_CONFIG_PATHS = ("config.toml", "~/.config/trolley/config.toml", "/etc/trolley/config.toml")


class ConfigError(Exception):
    """The config file is present but cannot be used as written."""


#: Google shows an app password as four groups of four, "abcd efgh ijkl mnop",
#: and the spaces are presentation only. Pasting it as shown is the single most
#: likely way to get a baffling "invalid credentials" on an otherwise correct
#: setup, so that exact shape has its spaces removed.
_APP_PASSWORD = re.compile(r"^([A-Za-z0-9]{4})\s+([A-Za-z0-9]{4})\s+([A-Za-z0-9]{4})\s+([A-Za-z0-9]{4})$")


def clean_password(raw: str) -> str:
    """Trim a password, and un-space a Google app password pasted as displayed."""
    trimmed = (raw or "").strip()
    grouped = _APP_PASSWORD.match(trimmed)
    return "".join(grouped.groups()) if grouped else trimmed


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8815
    database: str = "trolley.db"
    timezone: str = "Europe/Dublin"


@dataclass(frozen=True, slots=True)
class SuggestConfig:
    #: Longest list worth showing before it stops being read.
    max_suggestions: int = 12
    #: Below this the engine does not know enough to be worth interrupting for.
    min_confidence: float = 0.12
    min_score: float = 0.02
    #: Include things that last past this delivery but not the one after.
    include_soon: bool = True
    #: Learn which delivery each item belongs to, so the weekend shopping is
    #: suggested for the weekend order rather than the midweek one.
    slot_awareness: bool = True
    #: How many purchases before a delivery-day habit is believed, and what
    #: share of them must fall on that day.
    slot_min_purchases: int = 4
    slot_threshold: float = 0.75
    #: Each turned-down suggestion stretches the estimate by this much...
    nudge_step: float = 1.15
    #: ...up to this ceiling, so an item can never be pushed out for ever.
    nudge_max: float = 2.0


@dataclass(frozen=True, slots=True)
class NotifyConfig:
    enabled: bool = False
    #: Fire this long before the delivery lands, i.e. the evening before.
    hours_before: float = 14.0
    #: "console", "ntfy" or "smtp".
    channel: str = "console"
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    @property
    def smtp_password(self) -> str:
        return os.environ.get("TROLLEY_SMTP_PASSWORD", "")

    @property
    def ntfy_token(self) -> str:
        return os.environ.get("TROLLEY_NTFY_TOKEN", "")


@dataclass(frozen=True, slots=True)
class MailboxConfig:
    """Where to find order emails, so nothing has to be imported by hand."""

    enabled: bool = False
    host: str = ""
    port: int = 993
    username: str = ""
    #: "ssl" for the usual port 993, "starttls" for port 143, or "none" for a
    #: local bridge such as Proton Bridge that is already on the loopback.
    security: str = "ssl"
    folder: str = "INBOX"
    #: IMAP search terms narrowing the folder to grocery mail. Anything the
    #: parser cannot read is skipped, so this only has to be roughly right.
    search: str = 'FROM "tesco"'
    #: How far back to read the first time. After that only new mail is fetched.
    backfill_days: int = 730
    #: How often to look. Order emails are not urgent; the reminder is what is.
    poll_seconds: int = 900
    #: Mark messages read once imported. Off by default: it is your inbox.
    mark_seen: bool = False

    @property
    def password(self) -> str:
        return clean_password(os.environ.get("TROLLEY_IMAP_PASSWORD", ""))


@dataclass(frozen=True, slots=True)
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    suggest: SuggestConfig = field(default_factory=SuggestConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    mailbox: MailboxConfig = field(default_factory=MailboxConfig)
    slots: tuple[SlotSpec, ...] = (
        SlotSpec(day="monday", at="08:00", label="Monday delivery"),
        SlotSpec(day="friday", at="08:00", label="Friday delivery"),
    )
    #: Product-name fragment -> item key, for anything the normaliser misreads.
    aliases: dict[str, str] = field(default_factory=dict)
    #: Item key -> days, overriding the built-in typical restock intervals.
    intervals: dict[str, float] = field(default_factory=dict)

    @property
    def slot_specs(self) -> list[SlotSpec]:
        return list(self.slots)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _build(cls: type, data: dict[str, Any], name: str) -> Any:
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[{name}] has unknown keys: {', '.join(sorted(unknown))}")
    return cls(**data)


def parse_config(data: dict[str, Any]) -> Config:
    slots_raw = data.get("slots") or []
    if not isinstance(slots_raw, list):
        raise ConfigError("[[slots]] must be a list of tables")

    slots: list[SlotSpec] = []
    for entry in slots_raw:
        if not isinstance(entry, dict) or "day" not in entry:
            raise ConfigError("every [[slots]] entry needs a `day`")
        spec = SlotSpec(day=entry["day"], at=entry.get("at", "08:00"), label=entry.get("label", ""))
        weekday_number(spec.day)  # Fail loudly at load rather than at fire time.
        spec.parsed_time()
        slots.append(spec)

    config = Config(
        server=_build(ServerConfig, _section(data, "server"), "server"),
        suggest=_build(SuggestConfig, _section(data, "suggest"), "suggest"),
        notify=_build(NotifyConfig, _section(data, "notify"), "notify"),
        mailbox=_build(MailboxConfig, _section(data, "mailbox"), "mailbox"),
        slots=tuple(slots) if slots else Config().slots,
        aliases={str(k).casefold(): str(v) for k, v in _section(data, "aliases").items()},
        intervals={str(k): float(v) for k, v in _section(data, "intervals").items()},
    )
    if config.notify.enabled and config.notify.channel == "ntfy" and not config.notify.ntfy_topic:
        raise ConfigError("notify.channel = 'ntfy' needs notify.ntfy_topic")
    if config.notify.enabled and config.notify.channel == "smtp" and not config.notify.smtp_to:
        raise ConfigError("notify.channel = 'smtp' needs notify.smtp_to")
    if config.mailbox.security not in ("ssl", "starttls", "none"):
        raise ConfigError(
            f"mailbox.security must be 'ssl', 'starttls' or 'none', "
            f"not {config.mailbox.security!r}"
        )
    if config.mailbox.enabled:
        missing = [
            name
            for name in ("host", "username")
            if not getattr(config.mailbox, name)
        ]
        if missing:
            raise ConfigError(
                "[mailbox] is enabled but missing: " + ", ".join(f"mailbox.{m}" for m in missing)
            )
        if not config.mailbox.password:
            raise ConfigError(
                "[mailbox] is enabled but TROLLEY_IMAP_PASSWORD is not set in the environment"
            )
    return config


def load_config(path: str | Path | None = None) -> Config:
    """Load config from `path`, the TROLLEY_CONFIG env var, or the usual places."""
    candidates = [path] if path else [os.environ.get("TROLLEY_CONFIG"), *DEFAULT_CONFIG_PATHS]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = Path(candidate).expanduser()
        if resolved.is_file():
            try:
                with resolved.open("rb") as handle:
                    return parse_config(tomllib.load(handle))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{resolved}: {exc}") from exc
    if path:
        raise ConfigError(f"config file not found: {path}")
    return Config()
