"""Configuration loading.

Config lives in a TOML file; every secret is read from the environment so the
file itself can be committed or shared without leaking anything.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(os.environ.get("SWITCHTIME_CONFIG", "config.toml"))


class ConfigError(Exception):
    """Raised when the config file is missing something we cannot default."""


@dataclass(frozen=True)
class KidConfig:
    id: str
    name: str
    color: str = "#3e6fa6"
    ixl_username: str | None = None
    ixl_password: str | None = None
    switch_device_id: str | None = None
    nintendo_session_token: str | None = None
    minutes_per_lesson: int | None = None

    @property
    def ixl_ready(self) -> bool:
        return bool(self.ixl_username and self.ixl_password)

    @property
    def switch_ready(self) -> bool:
        return bool(self.switch_device_id)


@dataclass(frozen=True)
class Rules:
    minutes_per_lesson: int = 30
    daily_earn_cap_minutes: int = 180
    max_balance_minutes: int = 360
    rollover: bool = True
    # Minutes the console is allowed even on a zero balance. Keep at 0 to make
    # the Switch genuinely locked until something is earned.
    floor_minutes: int = 0


@dataclass(frozen=True)
class IXLConfig:
    enabled: bool = True
    poll_seconds: int = 180
    force_poll_cooldown_seconds: int = 30
    headless: bool = True
    nav_timeout_ms: int = 45_000
    signin_url: str = "https://www.ixl.com/signin"
    # Pages opened after sign-in; every JSON response seen while these load is
    # offered to the extractor.
    report_urls: tuple[str, ...] = (
        "https://www.ixl.com/analytics/questions-log",
        "https://www.ixl.com/analytics/usage-details",
    )
    # A lesson counts only once its SmartScore reaches this. IXL treats 80 as
    # "proficient"; set to 0 to count any practised skill.
    min_smartscore: int = 80
    storage_state_dir: str = "data/ixl-sessions"


@dataclass(frozen=True)
class NintendoConfig:
    enabled: bool = True
    dry_run: bool = False
    timezone: str = "Europe/Dublin"
    lang: str = "en-GB"
    session_token: str | None = None
    # Nintendo rejects anything outside this; see pynintendoparental helpers.
    max_daily_minutes: int = 360


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8777
    parent_pin: str = "1234"
    database: str = "data/switchtime.db"
    timezone: str = "Europe/Dublin"


@dataclass(frozen=True)
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    rules: Rules = field(default_factory=Rules)
    ixl: IXLConfig = field(default_factory=IXLConfig)
    nintendo: NintendoConfig = field(default_factory=NintendoConfig)
    kids: tuple[KidConfig, ...] = ()

    def kid(self, kid_id: str) -> KidConfig:
        for k in self.kids:
            if k.id == kid_id:
                return k
        raise KeyError(kid_id)

    def minutes_for(self, kid_id: str) -> int:
        kid = self.kid(kid_id)
        return kid.minutes_per_lesson or self.rules.minutes_per_lesson


def load_env_file(path: Path) -> None:
    """Fold KEY=VALUE lines from `path` into the environment.

    The background service gets these through systemd's EnvironmentFile, but a
    command run by hand would otherwise see nothing — so `switchtime devices`
    would fail right after `nintendo-login` had just saved a token. A real
    environment variable still wins, so an explicit export can override the file.
    """
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        if key not in os.environ:
            os.environ[key] = value
        elif os.environ[key] != value:
            # Precedence is deliberate, but a stale export shadowing a freshly
            # saved secret looks exactly like the secret being wrong, so say so.
            _LOG.warning(
                "%s is set in your shell and differs from the value in %s. "
                "The shell value is being used; run `unset %s` if it is stale.",
                key,
                path,
                key,
            )


def _env(name: str | None, *, what: str) -> str | None:
    """Read a secret out of the environment, tolerating an unset variable."""
    if not name:
        return None
    value = os.environ.get(name)
    if value is None:
        # Not fatal: a half-configured kid simply has that integration disabled,
        # which the UI surfaces rather than crashing the whole service.
        return None
    return value.strip() or None


def _subtable(raw: dict, key: str) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table")
    return value


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"No config at {path}. Copy config.example.toml to {path} and edit it."
        )
    # Before any secret is looked up, so a hand-run command sees what the
    # service sees.
    load_env_file(path.parent / ".env.local")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    server_raw = _subtable(raw, "server")
    server = ServerConfig(
        host=server_raw.get("host", ServerConfig.host),
        port=int(server_raw.get("port", ServerConfig.port)),
        parent_pin=str(
            _env(server_raw.get("parent_pin_env"), what="parent pin")
            or server_raw.get("parent_pin", ServerConfig.parent_pin)
        ),
        database=server_raw.get("database", ServerConfig.database),
        timezone=server_raw.get("timezone", ServerConfig.timezone),
    )

    rules_raw = _subtable(raw, "rules")
    rules = Rules(
        minutes_per_lesson=int(rules_raw.get("minutes_per_lesson", Rules.minutes_per_lesson)),
        daily_earn_cap_minutes=int(
            rules_raw.get("daily_earn_cap_minutes", Rules.daily_earn_cap_minutes)
        ),
        max_balance_minutes=int(rules_raw.get("max_balance_minutes", Rules.max_balance_minutes)),
        rollover=bool(rules_raw.get("rollover", Rules.rollover)),
        floor_minutes=int(rules_raw.get("floor_minutes", Rules.floor_minutes)),
    )

    ixl_raw = _subtable(raw, "ixl")
    ixl = IXLConfig(
        enabled=bool(ixl_raw.get("enabled", IXLConfig.enabled)),
        poll_seconds=max(30, int(ixl_raw.get("poll_seconds", IXLConfig.poll_seconds))),
        force_poll_cooldown_seconds=int(
            ixl_raw.get("force_poll_cooldown_seconds", IXLConfig.force_poll_cooldown_seconds)
        ),
        headless=bool(ixl_raw.get("headless", IXLConfig.headless)),
        nav_timeout_ms=int(ixl_raw.get("nav_timeout_ms", IXLConfig.nav_timeout_ms)),
        signin_url=ixl_raw.get("signin_url", IXLConfig.signin_url),
        report_urls=tuple(ixl_raw.get("report_urls", IXLConfig.report_urls)),
        min_smartscore=int(ixl_raw.get("min_smartscore", IXLConfig.min_smartscore)),
        storage_state_dir=ixl_raw.get("storage_state_dir", IXLConfig.storage_state_dir),
    )

    nin_raw = _subtable(raw, "nintendo")
    nintendo = NintendoConfig(
        enabled=bool(nin_raw.get("enabled", NintendoConfig.enabled)),
        dry_run=bool(nin_raw.get("dry_run", NintendoConfig.dry_run)),
        timezone=nin_raw.get("timezone", NintendoConfig.timezone),
        lang=nin_raw.get("lang", NintendoConfig.lang),
        session_token=_env(
            nin_raw.get("session_token_env", "NINTENDO_SESSION_TOKEN"),
            what="nintendo session token",
        ),
        max_daily_minutes=int(nin_raw.get("max_daily_minutes", NintendoConfig.max_daily_minutes)),
    )

    kids_raw = raw.get("kids", [])
    if not isinstance(kids_raw, list) or not kids_raw:
        raise ConfigError("Define at least one [[kids]] entry")
    kids: list[KidConfig] = []
    seen: set[str] = set()
    for entry in kids_raw:
        kid_id = str(entry.get("id", "")).strip()
        if not kid_id:
            raise ConfigError("Every [[kids]] entry needs an id")
        if kid_id in seen:
            raise ConfigError(f"Duplicate kid id {kid_id!r}")
        seen.add(kid_id)
        kids.append(
            KidConfig(
                id=kid_id,
                name=entry.get("name", kid_id.title()),
                color=entry.get("color", KidConfig.color),
                ixl_username=entry.get("ixl_username"),
                ixl_password=_env(entry.get("ixl_password_env"), what="ixl password"),
                switch_device_id=entry.get("switch_device_id"),
                nintendo_session_token=_env(
                    entry.get("nintendo_session_token_env"), what="nintendo token"
                )
                or nintendo.session_token,
                minutes_per_lesson=(
                    int(entry["minutes_per_lesson"]) if "minutes_per_lesson" in entry else None
                ),
            )
        )

    return Config(server=server, rules=rules, ixl=ixl, nintendo=nintendo, kids=tuple(kids))
