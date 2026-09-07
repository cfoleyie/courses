"""Nintendo Switch parental-controls client.

Wraps `pynintendoparental`, which talks to the same cloud API as Nintendo's own
Parental Controls app. That API is unofficial: Nintendo has changed it before
and will again, so every call here is treated as failure-prone and never blocks
the ledger from being correct.

The console enforces a *daily total*, not a countdown, so the limit we write is
always `already played + minutes still owed`. Recomputing that absolute number
each sync makes writes idempotent — a retry lands on the same value instead of
stacking bonuses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import Config, KidConfig

_LOG = logging.getLogger(__name__)

#: Nintendo's own bounds for a daily play-time limit, in minutes.
MIN_LIMIT = 0
MAX_LIMIT = 360


def looks_like_session_token(token: str) -> bool:
    """Cheap shape check for a Nintendo session token.

    They are JWTs: three dot-separated base64url segments, starting `eyJ`. This
    only catches obvious rubbish — placeholder text, a truncated paste — so that
    it fails with an explanation instead of Nintendo's opaque invalid_grant.
    """
    token = token.strip()
    return token.startswith("eyJ") and token.count(".") == 2 and len(token) > 100


class SwitchError(RuntimeError):
    """The console could not be read or written. Recoverable."""


@dataclass(frozen=True, slots=True)
class SwitchState:
    device_id: str
    played_today: int
    limit_minutes: int | None
    remaining: int | None
    extra_time_active: bool
    model: str = ""
    synced_at: float | None = None


class SwitchClient:
    """Thin, defensive wrapper around one Nintendo account's devices."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._nintendo: Any = None
        self._session: Any = None
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._config.nintendo.enabled

    @property
    def dry_run(self) -> bool:
        return self._config.nintendo.dry_run

    async def _connect(self) -> Any:
        if self._nintendo is not None:
            return self._nintendo
        token = self._config.nintendo.session_token
        if not token:
            raise SwitchError(
                "No Nintendo session token. Run `switchtime nintendo-login`, which saves "
                "one to .env.local."
            )
        if not looks_like_session_token(token):
            # Placeholder text from a copy-pasted instruction reaches Nintendo as
            # an opaque invalid_grant, so reject it here where we can explain.
            raise SwitchError(
                f"NINTENDO_SESSION_TOKEN does not look like a token (it starts {token[:20]!r}). "
                "It should be a long JWT beginning 'eyJ'. If you exported a placeholder in "
                "this shell, run `unset NINTENDO_SESSION_TOKEN`; otherwise re-run "
                "`switchtime nintendo-login`."
            )
        try:
            import aiohttp
            from pynintendoparental import Authenticator, NintendoParental
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SwitchError("pynintendoparental is not installed") from exc

        self._session = aiohttp.ClientSession()
        auth = Authenticator(session_token=token, client_session=self._session)
        try:
            await auth.async_complete_login(use_session_token=True)
            self._nintendo = await NintendoParental.create(
                auth,
                timezone=self._config.nintendo.timezone,
                lang=self._config.nintendo.lang,
            )
        except Exception as exc:  # noqa: BLE001 - includes Nintendo's own HTTP errors
            await self._drop_session()
            raise SwitchError(f"Nintendo login failed: {type(exc).__name__}: {exc}") from exc
        return self._nintendo

    async def _drop_session(self) -> None:
        self._nintendo = None
        if self._session is not None:
            try:
                await self._session.close()
            finally:
                self._session = None

    async def close(self) -> None:
        await self._drop_session()

    async def _device(self, kid: KidConfig) -> Any:
        if not kid.switch_device_id:
            raise SwitchError(f"No switch_device_id configured for {kid.name}")
        nintendo = await self._connect()
        try:
            await nintendo.update()
        except Exception as exc:  # noqa: BLE001
            # A stale access token shows up here; drop it so the next call
            # re-authenticates from the long-lived session token.
            await self._drop_session()
            raise SwitchError(f"Could not refresh devices: {type(exc).__name__}: {exc}") from exc
        device = nintendo.devices.get(kid.switch_device_id)
        if device is None:
            known = ", ".join(nintendo.devices) or "none"
            raise SwitchError(
                f"Device {kid.switch_device_id!r} not on this Nintendo account. Known devices: {known}"
            )
        return device

    async def snapshot(self, kid: KidConfig) -> SwitchState:
        device = await self._device(kid)
        return SwitchState(
            device_id=kid.switch_device_id or "",
            played_today=int(device.today_playing_time or 0),
            limit_minutes=(None if device.limit_time is None else int(device.limit_time)),
            remaining=(
                None if device.today_time_remaining is None else int(device.today_time_remaining)
            ),
            extra_time_active=bool(device.extra_playing_time),
            model=getattr(device, "model", "") or "",
            synced_at=getattr(device, "last_sync", None),
        )

    async def set_daily_limit(self, kid: KidConfig, minutes: int) -> int:
        """Write the console's daily limit. Returns the value actually sent."""
        target = max(MIN_LIMIT, min(int(minutes), MAX_LIMIT))
        if self.dry_run:
            _LOG.info("[dry-run] would set %s limit to %s min", kid.name, target)
            return target

        device = await self._device(kid)
        try:
            if device.extra_playing_time:
                # Bonus time pins the limit for the rest of the day and makes
                # update_max_daily_playtime raise. Our balance already accounts
                # for the same minutes, so clear it and set the real number.
                _LOG.info("clearing active bonus time on %s before setting limit", kid.name)
                await device.cancel_extra_time()
            await device.update_max_daily_playtime(target)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SwitchError(f"Could not set the limit for {kid.name}: {self.last_error}") from exc
        self.last_error = None
        _LOG.info("set %s daily limit to %s min", kid.name, target)
        return target

    async def list_devices(self) -> list[dict[str, Any]]:
        """Used by the setup CLI to discover device ids."""
        nintendo = await self._connect()
        await nintendo.update()
        return [
            {
                "device_id": device_id,
                "name": getattr(device, "name", "") or getattr(device, "label", ""),
                "model": getattr(device, "model", ""),
                "played_today": int(getattr(device, "today_playing_time", 0) or 0),
                "limit": getattr(device, "limit_time", None),
            }
            for device_id, device in nintendo.devices.items()
        ]


class NullSwitchClient:
    """Stand-in used when Nintendo control is switched off, and in tests.

    Records what would have been written so the UI and the tests can still show
    a target without touching the network.
    """

    enabled = False
    dry_run = True

    def __init__(self) -> None:
        self.writes: list[tuple[str, int]] = []
        self.state: dict[str, SwitchState] = {}
        self.last_error: str | None = None
        self.fail_with: str | None = None

    async def snapshot(self, kid: KidConfig) -> SwitchState:
        if self.fail_with:
            raise SwitchError(self.fail_with)
        return self.state.get(
            kid.id,
            SwitchState(
                device_id=kid.switch_device_id or "fake",
                played_today=0,
                limit_minutes=None,
                remaining=None,
                extra_time_active=False,
            ),
        )

    async def set_daily_limit(self, kid: KidConfig, minutes: int) -> int:
        if self.fail_with:
            raise SwitchError(self.fail_with)
        target = max(MIN_LIMIT, min(int(minutes), MAX_LIMIT))
        self.writes.append((kid.id, target))
        return target

    async def list_devices(self) -> list[dict[str, Any]]:
        return []

    async def close(self) -> None:
        return None


__all__ = [
    "SwitchClient",
    "SwitchError",
    "SwitchState",
    "NullSwitchClient",
    "MAX_LIMIT",
    "looks_like_session_token",
]
