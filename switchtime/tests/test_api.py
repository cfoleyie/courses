from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from switchtime.app import build_app


@pytest.fixture
def client(config, provider, switch):
    app = build_app(config, provider=provider, switch=switch)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def parent(client):
    response = client.post("/api/parent/unlock", json={"pin": "4321"})
    assert response.status_code == 200
    return client


class TestState:
    def test_lists_the_kids(self, client):
        body = client.get("/api/state").json()
        assert [k["id"] for k in body["kids"]] == ["oliver", "alice"]
        assert body["parent"] is False

    def test_hides_the_request_queue_from_kids(self, client):
        client.post("/api/kids/oliver/claim", json={"note": "did a page"})
        assert client.get("/api/state").json()["pending"] == []

    def test_shows_the_queue_to_a_parent(self, parent):
        parent.post("/api/kids/oliver/claim", json={"note": "did a page"})
        body = parent.get("/api/state").json()
        assert len(body["pending"]) == 1
        assert body["pending"][0]["kid_name"] == "Oliver"

    def test_unknown_kid_is_a_404(self, client):
        assert client.get("/api/kids/nobody/history").status_code == 404


class TestParentAuth:
    def test_wrong_pin_is_refused(self, client):
        assert client.post("/api/parent/unlock", json={"pin": "0000"}).status_code == 403

    def test_approving_without_a_pin_is_refused(self, client):
        assert client.post("/api/events/1/approve").status_code == 401

    def test_adjusting_without_a_pin_is_refused(self, client):
        response = client.post("/api/kids/oliver/adjust", json={"minutes": 500, "note": "x"})
        assert response.status_code in (401, 422)

    def test_a_non_ascii_pin_is_refused_not_a_crash(self, client):
        # compare_digest refuses non-ASCII str outright; a typed accent has to be
        # an ordinary wrong PIN rather than a 500 that skips the throttle.
        assert client.post("/api/parent/unlock", json={"pin": "é234"}).status_code == 403

    def test_lock_ends_the_session(self, parent):
        parent.post("/api/parent/lock")
        assert parent.get("/api/state").json()["parent"] is False


class TestClaims:
    def test_claim_then_approve_credits_the_balance(self, parent):
        claim = parent.post("/api/kids/oliver/claim", json={"note": "two pages"}).json()
        event_id = claim["event"]["id"]
        assert parent.post(f"/api/events/{event_id}/approve").status_code == 200
        kid = _kid(parent, "oliver")
        assert kid["balance"] == 30

    def test_rejected_claim_pays_nothing(self, parent):
        claim = parent.post("/api/kids/oliver/claim", json={"note": "nope"}).json()
        parent.post(f"/api/events/{claim['event']['id']}/reject")
        assert _kid(parent, "oliver")["balance"] == 0

    def test_approving_twice_is_a_404(self, parent):
        claim = parent.post("/api/kids/oliver/claim", json={"note": "once"}).json()
        event_id = claim["event"]["id"]
        parent.post(f"/api/events/{event_id}/approve")
        assert parent.post(f"/api/events/{event_id}/approve").status_code == 404


class TestSync:
    def test_forced_sync_reports_what_it_found(self, client, provider, engine_day):
        provider.queue_lesson("oliver", "ixl:a:x", day=engine_day)
        body = client.post("/api/kids/oliver/sync").json()
        assert body["new_lessons"] == 1
        assert body["minutes_earned"] == 30

    def test_a_second_forced_sync_is_rate_limited(self, client):
        client.post("/api/kids/oliver/sync")
        assert client.post("/api/kids/oliver/sync").status_code == 429

    def test_sync_all_needs_a_parent(self, client):
        assert client.post("/api/sync-all").status_code == 401


class TestAdjust:
    def test_parent_can_add_time(self, parent):
        parent.post("/api/kids/oliver/adjust", json={"minutes": 45, "note": "helped out"})
        assert _kid(parent, "oliver")["balance"] == 45

    def test_parent_can_remove_time(self, parent):
        parent.post("/api/kids/oliver/adjust", json={"minutes": -20, "note": "was cheeky"})
        assert _kid(parent, "oliver")["balance"] == -20

    def test_out_of_range_is_rejected(self, parent):
        response = parent.post("/api/kids/oliver/adjust", json={"minutes": 9999, "note": "x"})
        assert response.status_code == 422


class TestStatic:
    def test_index_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Switch Time" in response.text

    def test_manifest_is_served_for_installing(self, client):
        assert client.get("/manifest.webmanifest").status_code == 200

    def test_service_worker_is_at_the_root(self, client):
        # Scope matters: served from /static it could not control the app shell.
        assert client.get("/sw.js").status_code == 200

    def test_health(self, client):
        assert client.get("/api/health").json()["ok"] is True


class TestPoller:
    def test_it_runs_even_with_ixl_switched_off(self, config, provider, switch):
        # The poller is not only the IXL reader: it charges play time and writes
        # the console limit, both of which still matter when IXL is off.
        import dataclasses

        from switchtime.config import IXLConfig, NintendoConfig

        cfg = dataclasses.replace(
            config,
            ixl=IXLConfig(enabled=False),
            nintendo=NintendoConfig(enabled=True, dry_run=True),
        )
        app = build_app(cfg, provider=provider, switch=switch)
        with TestClient(app):
            task = app.state.engine._task
            assert task is not None and not task.done()


def _kid(client, kid_id):
    body = client.get("/api/state").json()
    return [k for k in body["kids"] if k["id"] == kid_id][0]


@pytest.fixture
def engine_day(config):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(config.server.timezone)).date().isoformat()
