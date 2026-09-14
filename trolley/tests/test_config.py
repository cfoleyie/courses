"""Config is read once at start-up, so mistakes should be caught there."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from trolley.config import ConfigError, load_config, parse_config


def parse(text: str):
    return parse_config(tomllib.loads(text))


def test_an_empty_config_still_gives_a_working_setup() -> None:
    config = parse("")
    assert [spec.day for spec in config.slot_specs] == ["monday", "friday"]
    assert config.server.timezone == "Europe/Dublin"


def test_slots_are_read_in_the_order_written() -> None:
    config = parse(
        """
        [[slots]]
        day = "tuesday"
        at = "07:30"
        label = "Midweek"
        [[slots]]
        day = "saturday"
        """
    )
    assert [spec.day for spec in config.slot_specs] == ["tuesday", "saturday"]
    assert config.slot_specs[0].title() == "Midweek"
    assert config.slot_specs[1].title() == "Saturday delivery"


def test_a_bad_weekday_is_rejected_at_load_not_at_fire_time() -> None:
    with pytest.raises(ValueError, match="unknown weekday"):
        parse('[[slots]]\nday = "someday"\n')


def test_a_slot_without_a_day_is_rejected() -> None:
    with pytest.raises(ConfigError, match="needs a `day`"):
        parse('[[slots]]\nat = "08:00"\n')


def test_a_typo_in_a_key_is_reported_rather_than_ignored() -> None:
    with pytest.raises(ConfigError, match="unknown keys: databse"):
        parse('[server]\ndatabse = "trolley.db"\n')


def test_notifications_must_be_configured_enough_to_work() -> None:
    with pytest.raises(ConfigError, match="ntfy_topic"):
        parse('[notify]\nenabled = true\nchannel = "ntfy"\n')
    with pytest.raises(ConfigError, match="smtp_to"):
        parse('[notify]\nenabled = true\nchannel = "smtp"\n')


def test_a_disabled_notifier_is_not_nitpicked() -> None:
    assert parse('[notify]\nchannel = "ntfy"\n').notify.enabled is False


def test_aliases_and_intervals_are_normalised() -> None:
    config = parse('[aliases]\n"Oat Drink" = "milk"\n\n[intervals]\n"toilet-roll" = 21\n')
    assert config.aliases == {"oat drink": "milk"}
    assert config.intervals == {"toilet-roll": 21.0}


def test_secrets_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("TROLLEY_SMTP_PASSWORD", "hunter2")
    assert parse("").notify.smtp_password == "hunter2"


def test_a_named_config_file_that_is_missing_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_a_malformed_file_names_itself(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[server\n")
    with pytest.raises(ConfigError, match="config.toml"):
        load_config(path)


def test_a_real_file_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[server]\nport = 9000\n')
    assert load_config(path).server.port == 9000
