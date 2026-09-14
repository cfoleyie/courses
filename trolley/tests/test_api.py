"""The HTTP surface the web app talks to."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from trolley.app import _maybe_notify, build_app
from trolley.config import Config, NotifyConfig
from trolley.db import Database
from trolley.importers import FakeImporter
from trolley.ingest import ingest

from conftest import DUBLIN, TODAY


@pytest.fixture
def client(db: Database, config: Config) -> TestClient:
    ingest(db, FakeImporter().generate(weeks=30, today=TODAY), config)
    with TestClient(build_app(config, db=db)) as test_client:
        yield test_client


def test_suggestions_carry_both_slots_and_a_reason(client: TestClient) -> None:
    body = client.get("/api/suggestions").json()
    assert body["slot"]["day"] and body["horizon"]["day"] > body["slot"]["day"]
    assert all(item["reason"] for item in body["suggestions"])


def test_the_plain_text_view_is_readable(client: TestClient) -> None:
    response = client.get("/api/suggestions.txt")
    assert response.status_code == 200
    assert "delivery" in response.text


def test_adding_an_item_moves_it_to_the_list(client: TestClient) -> None:
    first = client.get("/api/suggestions").json()["suggestions"][0]
    added = client.post(f"/api/items/{first['item_id']}/decide", json={"action": "add"})
    assert added.status_code == 200
    assert first["name"] in added.json()["message"]

    listed = client.get("/api/list").json()["items"]
    assert [entry["item_id"] for entry in listed] == [first["item_id"]]


def test_an_unknown_action_is_refused(client: TestClient) -> None:
    first = client.get("/api/suggestions").json()["suggestions"][0]
    response = client.post(f"/api/items/{first['item_id']}/decide", json={"action": "burn"})
    assert response.status_code == 422


def test_deciding_on_a_missing_item_is_a_404(client: TestClient) -> None:
    assert client.post("/api/items/99999/decide", json={"action": "add"}).status_code == 404


def test_marking_the_list_as_ordered_records_the_purchases(client: TestClient, db: Database) -> None:
    first = client.get("/api/suggestions").json()["suggestions"][0]
    client.post(f"/api/items/{first['item_id']}/decide", json={"action": "add"})
    before = len(db.purchases(first["item_id"]))

    response = client.post("/api/list/ordered")
    assert response.json()["recorded"] == 1
    assert len(db.purchases(first["item_id"])) == before + 1
    assert client.get("/api/list").json()["items"] == []


def test_clearing_the_list_records_nothing(client: TestClient, db: Database) -> None:
    first = client.get("/api/suggestions").json()["suggestions"][0]
    client.post(f"/api/items/{first['item_id']}/decide", json={"action": "add"})
    before = len(db.purchases(first["item_id"]))
    client.post("/api/list/clear")
    assert client.get("/api/list").json()["items"] == []
    assert len(db.purchases(first["item_id"])) == before


def test_items_report_what_the_engine_believes(client: TestClient) -> None:
    items = client.get("/api/items").json()["items"]
    milk = next(item for item in items if item["key"] == "milk")
    assert milk["interval"] and milk["purchases"] > 5
    assert 0 < milk["confidence"] <= 1


def test_an_item_can_be_given_a_fixed_interval(client: TestClient) -> None:
    items = client.get("/api/items").json()["items"]
    milk = next(item for item in items if item["key"] == "milk")
    assert client.patch(f"/api/items/{milk['item_id']}", json={"interval_override": 3}).status_code == 200

    after = client.get("/api/items").json()["items"]
    assert next(i for i in after if i["key"] == "milk")["basis"] == "override"


def test_patching_a_missing_item_is_a_404(client: TestClient) -> None:
    assert client.patch("/api/items/99999", json={"paused": True}).status_code == 404


def test_a_purchase_can_be_recorded_by_hand(client: TestClient) -> None:
    response = client.post(
        "/api/purchases",
        json={"item_key": "bleach", "name": "Bleach", "bought_on": "2026-09-10"},
    )
    assert response.status_code == 200
    assert any(i["key"] == "bleach" for i in client.get("/api/items").json()["items"])


def test_a_pasted_receipt_can_be_previewed_then_imported(client: TestClient) -> None:
    receipt = (
        "Delivery date: 14 September 2026\n"
        "Order number: 900112233\n"
        "2 Tesco Bleach Original 750Ml  £1.20\n"
    )
    preview = client.post("/api/import", json={"text": receipt, "dry_run": True}).json()
    assert preview["matches"][0]["item"] == "Bleach"
    assert not any(i["key"] == "bleach" for i in client.get("/api/items").json()["items"])

    client.post("/api/import", json={"text": receipt})
    assert any(i["key"] == "bleach" for i in client.get("/api/items").json()["items"])


def test_an_unreadable_paste_gets_a_helpful_error(client: TestClient) -> None:
    response = client.post("/api/import", json={"text": "just some words, no receipt here"})
    assert response.status_code == 422
    assert "date" in response.json()["detail"]


def test_the_web_app_and_its_manifest_are_served(client: TestClient) -> None:
    assert "<title>Trolley</title>" in client.get("/").text
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/sw.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_without_slots_the_api_says_so(db: Database) -> None:
    with TestClient(build_app(Config(slots=()), db=db)) as bare:
        assert bare.get("/api/suggestions").status_code == 503


# ----- the reminder ----------------------------------------------------


def _notify_config(config: Config) -> Config:
    return Config(
        server=config.server,
        slots=config.slots,
        suggest=config.suggest,
        notify=NotifyConfig(enabled=True, channel="console", hours_before=14),
    )


@pytest.mark.asyncio
async def test_the_reminder_fires_once_in_the_window(db: Database, config: Config, capsys) -> None:
    ingest(db, FakeImporter().generate(weeks=30, today=TODAY), config)
    notifying = _notify_config(config)
    sunday_evening = datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)

    assert await _maybe_notify(db, notifying, sunday_evening) is True
    assert "delivery" in capsys.readouterr().out
    # A restart inside the window must not send the same list again.
    assert await _maybe_notify(db, notifying, sunday_evening) is False


@pytest.mark.asyncio
async def test_the_reminder_waits_until_it_is_close_enough(db: Database, config: Config) -> None:
    ingest(db, FakeImporter().generate(weeks=30, today=TODAY), config)
    two_days_early = datetime(2026, 9, 12, 9, 0, tzinfo=DUBLIN)
    assert await _maybe_notify(db, _notify_config(config), two_days_early) is False


@pytest.mark.asyncio
async def test_nothing_due_means_no_interruption(db: Database, config: Config, capsys) -> None:
    sunday_evening = datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)
    assert await _maybe_notify(db, _notify_config(config), sunday_evening) is False
    assert capsys.readouterr().out == ""


def test_the_api_reports_the_delivery_an_item_belongs_to(client: TestClient, db: Database) -> None:
    items = client.get("/api/items").json()["items"]
    assert all("preferred_slot" in item for item in items)

    milk = next(item for item in items if item["key"] == "milk")
    assert client.patch(
        f"/api/items/{milk['item_id']}", json={"slot_preference": "friday"}
    ).status_code == 200

    after = next(i for i in client.get("/api/items").json()["items"] if i["key"] == "milk")
    assert (after["preferred_slot"], after["slot_pinned"]) == ("friday", True)


def test_a_nonsense_delivery_day_is_refused(client: TestClient) -> None:
    milk = next(i for i in client.get("/api/items").json()["items"] if i["key"] == "milk")
    response = client.patch(f"/api/items/{milk['item_id']}", json={"slot_preference": "funday"})
    assert response.status_code == 400
    assert "weekday" in response.json()["detail"]


def test_suggestions_carry_the_held_back_list(client: TestClient) -> None:
    assert "deferred" in client.get("/api/suggestions").json()
