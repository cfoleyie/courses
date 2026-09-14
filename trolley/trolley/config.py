"""Configuration, read from a TOML file with sensible defaults for everything.

Secrets (SMTP password, ntfy token) come from the environment rather than the
file, so the config can live in version control next to the rest of the setup.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .slots import SlotSpec, weekday_number

DEFAULT_CONFIG_PATHS = ("config.toml", "~/.config/trolley/config.toml", "/etc/trolley/config.toml")


class ConfigError(Exception):
    """The config file is present but cannot be used as written."""


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
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    suggest: SuggestConfig = field(default_factory=SuggestConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
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
        slots=tuple(slots) if slots else Config().slots,
        aliases={str(k).casefold(): str(v) for k, v in _section(data, "aliases").items()},
        intervals={str(k): float(v) for k, v in _section(data, "intervals").items()},
    )
    if config.notify.enabled and config.notify.channel == "ntfy" and not config.notify.ntfy_topic:
        raise ConfigError("notify.channel = 'ntfy' needs notify.ntfy_topic")
    if config.notify.enabled and config.notify.channel == "smtp" and not config.notify.smtp_to:
        raise ConfigError("notify.channel = 'smtp' needs notify.smtp_to")
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
