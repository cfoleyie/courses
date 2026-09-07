from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchtime.config import Config, IXLConfig, KidConfig, NintendoConfig, Rules, ServerConfig
from switchtime.db import Database
from switchtime.providers.fake import FakeProvider
from switchtime.switch import NullSwitchClient
from switchtime.sync import SyncEngine


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        server=ServerConfig(
            parent_pin="4321",
            database=str(tmp_path / "test.db"),
            timezone="Europe/Dublin",
        ),
        rules=Rules(
            minutes_per_lesson=30,
            daily_earn_cap_minutes=90,
            max_balance_minutes=360,
            rollover=True,
        ),
        ixl=IXLConfig(enabled=True, poll_seconds=60, force_poll_cooldown_seconds=30),
        nintendo=NintendoConfig(enabled=False, dry_run=True),
        kids=(
            KidConfig(
                id="oliver",
                name="Oliver",
                ixl_username="oliver@example.test",
                ixl_password="hunter2",
                switch_device_id="device-oliver",
            ),
            KidConfig(
                id="alice",
                name="Alice",
                ixl_username="alice@example.test",
                ixl_password="hunter2",
                switch_device_id="device-alice",
            ),
        ),
    )


@pytest.fixture
def db(config: Config) -> Database:
    return Database(config.server.database)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def switch() -> NullSwitchClient:
    return NullSwitchClient()


@pytest.fixture
def engine(config, db, provider, switch) -> SyncEngine:
    return SyncEngine(config, db, provider, switch)
