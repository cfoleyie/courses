"""HTTP API and static hosting for the Switch Time web app."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Config, load_config
from .db import Database
from .ledger import Kind, Status, balance, earned_on, humanise
from .providers.fake import FakeProvider
from .providers.ixl import IXLProvider
from .switch import NullSwitchClient, SwitchClient
from .sync import SyncEngine

_LOG = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

#: Parent sessions live in memory: this is a home-LAN app, and a restart
#: logging parents out again is the safer default.
PARENT_SESSION_TTL = 30 * 60


class ParentSessions:
    def __init__(self, ttl: int = PARENT_SESSION_TTL) -> None:
        self._tokens: dict[str, float] = {}
        self._ttl = ttl

    def issue(self) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = time.monotonic() + self._ttl
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        expiry = self._tokens.get(token)
        if expiry is None:
            return False
        if expiry < time.monotonic():
            self._tokens.pop(token, None)
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if token:
            self._tokens.pop(token, None)


class ClaimBody(BaseModel):
    note: str = Field(default="", max_length=200)


class AdjustBody(BaseModel):
    minutes: int = Field(ge=-360, le=360)
    note: str = Field(default="", max_length=200)


class PinBody(BaseModel):
    pin: str = Field(min_length=1, max_length=32)


def build_app(config: Config | None = None, *, provider: Any = None, switch: Any = None) -> FastAPI:
    config = config or load_config()
    db = Database(config.server.database)

    if provider is None:
        provider = IXLProvider(config) if config.ixl.enabled else FakeProvider()
    if switch is None:
        switch = SwitchClient(config) if config.nintendo.enabled else NullSwitchClient()

    engine = SyncEngine(config, db, provider, switch)
    sessions = ParentSessions()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # The poller is not only the IXL reader: it also charges play time and
        # writes the console limit, so it has to run whenever either side is on.
        if config.ixl.enabled or config.nintendo.enabled:
            await engine.start()
        try:
            yield
        finally:
            await engine.stop()
            for closable in (provider, switch):
                closer = getattr(closable, "close", None)
                if closer is not None:
                    try:
                        await closer()
                    except Exception:  # noqa: BLE001 - shutdown must not raise
                        _LOG.exception("error closing %r", closable)

    app = FastAPI(title="Switch Time", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.db = db
    app.state.engine = engine

    # ----- auth ---------------------------------------------------------

    def parent_required(st_parent: str | None = Cookie(default=None)) -> str:
        if not sessions.valid(st_parent):
            raise HTTPException(status_code=401, detail="Parent PIN required")
        return st_parent  # type: ignore[return-value]

    @app.post("/api/parent/unlock")
    async def unlock(body: PinBody, response: Response) -> dict[str, bool]:
        # Compare bytes: compare_digest refuses non-ASCII str, and a PIN typed
        # with an accented character must simply be wrong, not a 500.
        supplied = body.pin.encode("utf-8")
        expected = config.server.parent_pin.encode("utf-8")
        if not secrets.compare_digest(supplied, expected):
            # Cheap throttle: a wrong PIN costs a second, which makes guessing
            # a four-digit code over the LAN tedious without locking anyone out.
            await asyncio.sleep(1.0)
            raise HTTPException(status_code=403, detail="Wrong PIN")
        token = sessions.issue()
        response.set_cookie(
            "st_parent", token, httponly=True, samesite="lax", max_age=PARENT_SESSION_TTL
        )
        return {"ok": True}

    @app.post("/api/parent/lock")
    async def lock(response: Response, st_parent: str | None = Cookie(default=None)) -> dict[str, bool]:
        sessions.revoke(st_parent)
        response.delete_cookie("st_parent")
        return {"ok": True}

    # ----- read ---------------------------------------------------------

    def kid_payload(kid_id: str) -> dict[str, Any]:
        kid = config.kid(kid_id)
        events = db.events_for(kid_id)
        current = balance(events)
        report = engine.last_report(kid_id) or {}
        return {
            "id": kid.id,
            "name": kid.name,
            "color": kid.color,
            "balance": current,
            "balance_text": humanise(current),
            "minutes_per_lesson": config.minutes_for(kid_id),
            "earned_today": earned_on(events, engine.today()),
            "daily_cap": config.rules.daily_earn_cap_minutes,
            "pending": len(db.pending(kid_id)),
            "cooldown": engine.cooldown_remaining(kid_id),
            "ixl_ready": kid.ixl_ready and config.ixl.enabled,
            "switch_ready": kid.switch_ready,
            "last_sync": report.get("at"),
            "last_sync_ok": report.get("ok", True),
            "played_today": report.get("played_today", 0),
            "target_limit": report.get("target_limit"),
        }

    @app.get("/api/state")
    async def state(st_parent: str | None = Cookie(default=None)) -> dict[str, Any]:
        is_parent = sessions.valid(st_parent)
        return {
            "kids": [kid_payload(k.id) for k in config.kids],
            "parent": is_parent,
            "pending": [_event_json(e, config) for e in db.pending()] if is_parent else [],
            "rules": {
                "minutes_per_lesson": config.rules.minutes_per_lesson,
                "daily_cap": config.rules.daily_earn_cap_minutes,
                "rollover": config.rules.rollover,
            },
        }

    @app.get("/api/kids/{kid_id}/history")
    async def history(kid_id: str) -> dict[str, Any]:
        _require_kid(config, kid_id)
        events = db.events_for(kid_id, limit=60)
        return {"events": [_event_json(e, config) for e in events]}

    @app.get("/api/kids/{kid_id}/report")
    async def report(kid_id: str) -> dict[str, Any]:
        _require_kid(config, kid_id)
        return engine.last_report(kid_id) or {"kid_id": kid_id, "at": None}

    # ----- kid actions ---------------------------------------------------

    @app.post("/api/kids/{kid_id}/sync")
    async def force_sync(kid_id: str) -> dict[str, Any]:
        _require_kid(config, kid_id)
        wait = engine.cooldown_remaining(kid_id)
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Hang on {wait}s and try again")
        result = await engine.sync_kid(kid_id, reason="forced")
        return result.as_dict()

    @app.post("/api/kids/{kid_id}/claim")
    async def claim(kid_id: str, body: ClaimBody) -> dict[str, Any]:
        _require_kid(config, kid_id)
        event = engine.add_manual_claim(kid_id, body.note or "Finished an IXL lesson")
        return {"ok": True, "event": _event_json(event, config)}

    # ----- parent actions -------------------------------------------------

    @app.post("/api/events/{event_id}/approve")
    async def approve(event_id: int, _: str = Depends(parent_required)) -> dict[str, bool]:
        if not engine.decide(event_id, approve=True):
            raise HTTPException(status_code=404, detail="Nothing pending with that id")
        return {"ok": True}

    @app.post("/api/events/{event_id}/reject")
    async def reject(event_id: int, _: str = Depends(parent_required)) -> dict[str, bool]:
        if not engine.decide(event_id, approve=False):
            raise HTTPException(status_code=404, detail="Nothing pending with that id")
        return {"ok": True}

    @app.post("/api/kids/{kid_id}/adjust")
    async def adjust(
        kid_id: str, body: AdjustBody, _: str = Depends(parent_required)
    ) -> dict[str, Any]:
        _require_kid(config, kid_id)
        event = engine.adjust(kid_id, body.minutes, body.note or "Parent adjustment")
        return {"ok": True, "event": _event_json(event, config)}

    @app.post("/api/sync-all")
    async def sync_all(_: str = Depends(parent_required)) -> dict[str, Any]:
        reports = await engine.sync_all(reason="manual")
        return {"reports": [r.as_dict() for r in reports]}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "kids": len(config.kids),
            "ixl_enabled": config.ixl.enabled,
            "nintendo_enabled": config.nintendo.enabled,
            "dry_run": getattr(switch, "dry_run", True),
        }

    # ----- static --------------------------------------------------------

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/manifest.webmanifest")
        async def manifest() -> FileResponse:
            return FileResponse(
                STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
            )

        @app.get("/sw.js")
        async def service_worker() -> FileResponse:
            # Served from the root so its scope covers the whole app.
            return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

    return app


def _require_kid(config: Config, kid_id: str) -> None:
    try:
        config.kid(kid_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No kid called {kid_id!r}") from None


_KIND_LABELS = {
    Kind.EARN_IXL: "IXL lesson",
    Kind.EARN_MANUAL: "Claimed by hand",
    Kind.ADJUST: "Parent adjustment",
    Kind.CONSUME: "Played on the Switch",
    Kind.EXPIRE: "Expired overnight",
}


def _event_json(event: Any, config: Config) -> dict[str, Any]:
    return {
        "id": event.id,
        "kid_id": event.kid_id,
        "kid_name": config.kid(event.kid_id).name if _has_kid(config, event.kid_id) else event.kid_id,
        "kind": str(event.kind),
        "label": _KIND_LABELS.get(event.kind, str(event.kind)),
        "minutes": event.minutes,
        "minutes_text": humanise(event.minutes),
        "day": event.day,
        "status": str(event.status),
        "note": event.note,
        "created_at": event.created_at.isoformat(),
        "pending": event.status is Status.PENDING,
    }


def _has_kid(config: Config, kid_id: str) -> bool:
    try:
        config.kid(kid_id)
        return True
    except KeyError:
        return False


app_factory = build_app
