"""HTTP API and static hosting for the Trolley web app.

A background task watches the clock and fires one notification per delivery,
far enough ahead to still change the order. The list itself is always available
in the browser, so the notification is a nudge rather than the only way in.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ingest as ingest_module
from . import mailbox as mailbox_module
from . import notify, suggest
from .config import Config, load_config
from .db import Database
from .importers import CsvImporter, EmailImporter, ImportError_, detect
from .model import Estimate, Suggestion
from .slots import Slot

_LOG = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

#: How often the background task checks whether a slot's reminder is due.
TICK_SECONDS = 300

#: Back off to this after a mailbox failure, so a wrong password does not
#: hammer the mail server every fifteen minutes.
MAILBOX_RETRY_SECONDS = 1800


class DecideBody(BaseModel):
    action: str = Field(pattern="^(add|remove|dismiss|snooze|pause|resume)$")
    quantity: float = Field(default=1.0, ge=0.1, le=99)
    slot_day: date | None = None


class ItemBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=40)
    interval_override: float | None = Field(default=None, ge=0.5, le=365)
    paused: bool | None = None


class PurchaseBody(BaseModel):
    item_key: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=120)
    bought_on: date | None = None
    quantity: float = Field(default=1.0, ge=0.1, le=99)


class ImportBody(BaseModel):
    """A receipt pasted straight into the browser, rather than a file."""

    text: str = Field(min_length=10, max_length=500_000)
    dry_run: bool = False


def _slot_json(slot: Slot) -> dict[str, Any]:
    return {"label": slot.label, "day": slot.day.isoformat(), "at": slot.at.isoformat()}


def _estimate_json(est: Estimate) -> dict[str, Any]:
    return {
        "item_id": est.item.id,
        "key": est.item.key,
        "name": est.item.name,
        "category": est.item.category,
        "interval": round(est.interval, 1) if est.interval else None,
        "unit_interval": round(est.unit_interval, 1) if est.unit_interval else None,
        "last_bought": est.last_bought.isoformat() if est.last_bought else None,
        "due_on": est.due_on.isoformat() if est.due_on else None,
        "confidence": est.confidence,
        "basis": est.basis,
        "purchases": est.purchases,
        "paused": est.item.paused,
    }


def _suggestion_json(suggestion: Suggestion) -> dict[str, Any]:
    return {
        **_estimate_json(suggestion.estimate),
        "status": suggestion.status.value,
        "score": suggestion.score,
        "reason": suggestion.reason,
        "quantity": suggestion.quantity,
    }


def build_app(config: Config | None = None, *, db: Database | None = None) -> FastAPI:
    config = config or load_config()
    store = db or Database(config.server.database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [
            asyncio.create_task(_reminder_loop(store, config)),
            asyncio.create_task(_mailbox_loop(store, config)),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Trolley", version="0.1.0", lifespan=lifespan)

    def report_or_404() -> suggest.Report:
        report = suggest.build(store, config)
        if report is None:
            raise HTTPException(503, "no delivery slots are configured")
        return report

    # ----- suggestions ------------------------------------------------

    @app.get("/api/suggestions")
    def suggestions() -> dict[str, Any]:
        report = report_or_404()
        return {
            "slot": _slot_json(report.slot),
            "horizon": _slot_json(report.horizon),
            "generated_at": report.generated_at.isoformat(),
            "suggestions": [_suggestion_json(s) for s in report.suggestions],
            "unsure": [_estimate_json(e) for e in report.unsure],
            "list": store.list_for(report.slot.day),
        }

    @app.get("/api/suggestions.txt", response_class=PlainTextResponse)
    def suggestions_text() -> str:
        return suggest.render_text(report_or_404())

    @app.post("/api/items/{item_id}/decide")
    def decide(item_id: int, body: DecideBody) -> dict[str, Any]:
        report = report_or_404()
        slot_day = body.slot_day or report.slot.day
        try:
            message = suggest.decide(
                store, config, item_id, slot_day, body.action, body.quantity
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "message": message}

    # ----- the list ----------------------------------------------------

    @app.get("/api/list")
    def working_list() -> dict[str, Any]:
        report = report_or_404()
        return {"slot": _slot_json(report.slot), "items": store.list_for(report.slot.day)}

    @app.post("/api/list/clear")
    def clear_list() -> dict[str, Any]:
        report = report_or_404()
        store.clear_list(report.slot.day)
        return {"ok": True}

    @app.post("/api/list/ordered")
    def mark_ordered() -> dict[str, Any]:
        """Record everything on the list as bought, once the order is placed.

        This is the shortcut for someone who never imports a confirmation
        email: ticking things on and pressing "ordered" is itself history.
        """
        report = report_or_404()
        entries = store.list_for(report.slot.day)
        ref = f"list:{report.slot.day.isoformat()}"
        for entry in entries:
            store.add_purchase(
                entry["item_id"],
                report.slot.day,
                entry["quantity"],
                entry["name"],
                ref,
                "list",
            )
        store.record_order(ref, report.slot.day, "list", len(entries))
        store.clear_list(report.slot.day)
        return {"ok": True, "recorded": len(entries)}

    # ----- items and history -------------------------------------------

    @app.get("/api/items")
    def items() -> dict[str, Any]:
        today = datetime.now().date()
        return {
            "items": [
                _estimate_json(est) for est in suggest.estimates(store, config, today)
            ]
        }

    @app.patch("/api/items/{item_id}")
    def patch_item(item_id: int, body: ItemBody) -> dict[str, Any]:
        if store.item(item_id) is None:
            raise HTTPException(404, f"no item with id {item_id}")
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        store.update_item(item_id, **fields)
        return {"ok": True}

    @app.post("/api/purchases")
    def add_purchase(body: PurchaseBody) -> dict[str, Any]:
        item = store.item_by_key(body.item_key) or store.upsert_item(
            body.item_key, body.name or body.item_key.replace("-", " ").capitalize()
        )
        when = body.bought_on or datetime.now().date()
        store.add_purchase(item.id, when, body.quantity, item.name, None, "manual")
        return {"ok": True, "item_id": item.id}

    @app.get("/api/orders")
    def orders() -> dict[str, Any]:
        return {"orders": store.orders()}

    @app.get("/api/mailbox")
    def mailbox_status() -> dict[str, Any]:
        """Whether the mailbox watcher is on, and how it last got on."""
        return {
            "enabled": config.mailbox.enabled,
            "host": config.mailbox.host,
            "folder": config.mailbox.folder,
            "search": config.mailbox.search,
            "poll_seconds": config.mailbox.poll_seconds,
            "last_run": store.get_state("mailbox:last_run"),
            "last_result": store.get_state("mailbox:last_result"),
            "last_error": store.get_state("mailbox:last_error"),
        }

    @app.post("/api/mailbox/check")
    async def mailbox_check() -> dict[str, Any]:
        """Read the mailbox now rather than waiting for the next poll."""
        if not config.mailbox.enabled:
            raise HTTPException(400, "[mailbox] is not enabled in the config")
        try:
            result = await asyncio.to_thread(mailbox_module.collect, store, config)
        except mailbox_module.MailboxError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"ok": True, "summary": result.summary()}

    @app.post("/api/import")
    def import_text(body: ImportBody = Body(...)) -> dict[str, Any]:
        """Import a receipt pasted into the browser."""
        from .importers.email_import import html_to_text, parse_receipt_text

        text = body.text
        if "<" in text and ">" in text:
            text = html_to_text(text)
        try:
            order = parse_receipt_text(text)
        except ImportError_ as exc:
            raise HTTPException(422, str(exc)) from exc
        result = ingest_module.ingest(store, [order], config, dry_run=body.dry_run)
        return {
            "ok": True,
            "dry_run": body.dry_run,
            "summary": result.summary(),
            "bought_on": order.bought_on.isoformat(),
            "matches": [
                {
                    "raw_name": m.raw_name,
                    "quantity": m.quantity,
                    "item": m.item_name,
                    "how": m.how,
                }
                for m in result.matches
            ],
        }

    # ----- static ------------------------------------------------------

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        # Served from the root so its scope covers the whole app.
        return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript")

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


async def _reminder_loop(store: Database, config: Config) -> None:
    """Fire one notification per delivery, the configured lead time before it."""
    if not config.notify.enabled:
        return
    while True:
        try:
            await _maybe_notify(store, config)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a bad channel must not kill the app
            _LOG.exception("reminder check failed")
        await asyncio.sleep(TICK_SECONDS)


async def _mailbox_loop(store: Database, config: Config) -> None:
    """Poll the mailbox for new order emails, for as long as the server runs."""
    if not config.mailbox.enabled:
        return
    while True:
        delay = config.mailbox.poll_seconds
        try:
            result = await asyncio.to_thread(mailbox_module.collect, store, config)
            store.set_state("mailbox:last_run", datetime.now().isoformat(timespec="seconds"))
            store.set_state("mailbox:last_result", result.summary())
            store.set_state("mailbox:last_error", "")
            if result.receipts:
                _LOG.info("mailbox: %s", result.summary())
        except asyncio.CancelledError:
            raise
        except mailbox_module.MailboxError as exc:
            # Usually a wrong password or a renamed folder: worth saying once
            # per retry rather than every poll, and worth slowing down for.
            _LOG.warning("mailbox: %s", exc)
            store.set_state("mailbox:last_error", str(exc))
            delay = max(delay, MAILBOX_RETRY_SECONDS)
        except Exception:  # pragma: no cover - never kill the server for this
            _LOG.exception("mailbox check failed")
            delay = max(delay, MAILBOX_RETRY_SECONDS)
        await asyncio.sleep(delay)


async def _maybe_notify(store: Database, config: Config, now: datetime | None = None) -> bool:
    """Send the reminder for the next slot if it is time and it has not gone.

    The last notified slot is stored, so a restart inside the reminder window
    does not send the same list twice.
    """
    report = suggest.build(store, config, now)
    if report is None:
        return False
    moment = report.generated_at
    if report.slot.at - moment > timedelta(hours=config.notify.hours_before):
        return False

    marker = f"notified:{report.slot.day.isoformat()}"
    if store.get_state(marker):
        return False
    if not report.suggestions:
        store.set_state(marker, "empty")
        return False

    body = suggest.render_text(report)
    subject = f"Trolley: {len(report.suggestions)} for {report.slot.label}"
    await asyncio.to_thread(notify.send, config.notify, subject, body)
    store.set_state(marker, moment.isoformat(timespec="seconds"))
    return True
