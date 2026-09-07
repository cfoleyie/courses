from __future__ import annotations

from datetime import datetime

from switchtime.db import Database
from switchtime.ledger import Event, Kind, Status

NOW = datetime(2026, 9, 7, 12, 0)


def make(ref: str | None, minutes: int = 30, kid: str = "oliver") -> Event:
    return Event(
        kid_id=kid, kind=Kind.EARN_IXL, minutes=minutes, day="2026-09-07",
        created_at=NOW, ref=ref, note="test",
    )


class TestEvents:
    def test_insert_returns_the_new_id(self, db: Database):
        stored = db.add_event(make("a"))
        assert stored is not None and stored.id is not None

    def test_duplicate_ref_is_rejected(self, db: Database):
        assert db.add_event(make("a")) is not None
        assert db.add_event(make("a")) is None, "the same lesson must not pay twice"

    def test_the_same_ref_is_fine_for_a_different_kid(self, db: Database):
        assert db.add_event(make("a", kid="oliver")) is not None
        assert db.add_event(make("a", kid="alice")) is not None

    def test_null_refs_do_not_collide(self, db: Database):
        # Manual claims and adjustments carry no ref; several must coexist.
        assert db.add_event(make(None)) is not None
        assert db.add_event(make(None)) is not None

    def test_known_refs_round_trips(self, db: Database):
        db.add_event(make("a"))
        db.add_event(make("b"))
        assert db.known_refs("oliver") == {"a", "b"}

    def test_has_ref(self, db: Database):
        db.add_event(make("a"))
        assert db.has_ref("oliver", "a")
        assert not db.has_ref("oliver", "zzz")

    def test_events_are_newest_first_and_limited(self, db: Database):
        for i in range(5):
            db.add_event(make(f"r{i}"))
        events = db.events_for("oliver", limit=2)
        assert len(events) == 2
        assert events[0].ref == "r4"


class TestPending:
    def test_only_pending_events_are_listed(self, db: Database):
        from dataclasses import replace

        db.add_event(replace(make("p1"), status=Status.PENDING))
        db.add_event(make("approved"))
        pending = db.pending()
        assert [e.ref for e in pending] == ["p1"]

    def test_filtered_by_kid(self, db: Database):
        from dataclasses import replace

        db.add_event(replace(make("p1", kid="oliver"), status=Status.PENDING))
        db.add_event(replace(make("p2", kid="alice"), status=Status.PENDING))
        assert len(db.pending("alice")) == 1

    def test_set_status_only_moves_pending_rows(self, db: Database):
        from dataclasses import replace

        stored = db.add_event(replace(make("p1"), status=Status.PENDING))
        assert db.set_status(stored.id, Status.APPROVED)
        assert not db.set_status(stored.id, Status.REJECTED)


class TestState:
    def test_round_trips_json(self, db: Database):
        db.set_state("k", {"a": [1, 2]})
        assert db.get_state("k") == {"a": [1, 2]}

    def test_missing_key_returns_default(self, db: Database):
        assert db.get_state("nope", "fallback") == "fallback"

    def test_overwrite(self, db: Database):
        db.set_state("k", 1)
        db.set_state("k", 2)
        assert db.get_state("k") == 2

    def test_none_is_stored_not_treated_as_missing(self, db: Database):
        db.set_state("played:oliver", None)
        assert db.get_state("played:oliver", "default") is None


def test_schema_survives_reopening(config):
    first = Database(config.server.database)
    first.add_event(make("a"))
    second = Database(config.server.database)
    assert len(second.events_for("oliver")) == 1
