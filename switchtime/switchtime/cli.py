"""Command line entry points: setup, diagnostics and running the server."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import Config, ConfigError, load_config
from .db import Database
from .ledger import balance, humanise
from .providers.fake import FakeProvider
from .providers.ixl import IXLProvider
from .switch import NullSwitchClient, SwitchClient, SwitchError
from .sync import SyncEngine


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _engine(config: Config) -> SyncEngine:
    db = Database(config.server.database)
    provider = IXLProvider(config) if config.ixl.enabled else FakeProvider()
    switch = SwitchClient(config) if config.nintendo.enabled else NullSwitchClient()
    return SyncEngine(config, db, provider, switch)


# ----- commands ---------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import build_app

    config = load_config(args.config)
    app = build_app(config)
    uvicorn.run(
        app,
        host=args.host or config.server.host,
        port=args.port or config.server.port,
        log_level="debug" if args.verbose else "info",
    )
    return 0


def cmd_nintendo_login(args: argparse.Namespace) -> int:
    """Walk through Nintendo's OAuth flow once and print a reusable token."""

    async def run() -> int:
        import aiohttp
        from pynintendoparental import Authenticator

        async with aiohttp.ClientSession() as session:
            auth = Authenticator(client_session=session)
            print("\n1. Open this URL in a browser signed in as the parent account:\n")
            print(f"   {auth.login_url}\n")
            print("2. Complete the sign-in. The page will end on a 'Link account' button.")
            print("   Right-click it, copy the link address (it starts with npf...), and paste below.\n")
            redirect = input("Pasted URL: ").strip()
            if not redirect:
                print("Nothing pasted — aborting.", file=sys.stderr)
                return 1
            try:
                await auth.async_complete_login(redirect)
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
                print(f"Login failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
            print("\nSession token (store it in your environment, it does not expire quickly):\n")
            print(f"   export NINTENDO_SESSION_TOKEN='{auth.session_token}'\n")
            return 0

    return asyncio.run(run())


def cmd_devices(args: argparse.Namespace) -> int:
    async def run() -> int:
        config = load_config(args.config)
        client = SwitchClient(config)
        try:
            devices = await client.list_devices()
        except SwitchError as exc:
            print(f"Could not list devices: {exc}", file=sys.stderr)
            return 1
        finally:
            await client.close()
        if not devices:
            print("No devices on this Nintendo account.")
            return 1
        print(f"{len(devices)} device(s):\n")
        for device in devices:
            print(f"  switch_device_id = \"{device['device_id']}\"")
            print(f"      model        {device['model'] or 'unknown'}")
            print(f"      played today {device['played_today']} min")
            print(f"      limit        {device['limit']}")
            print()
        return 0

    return asyncio.run(run())


def cmd_probe(args: argparse.Namespace) -> int:
    """Dump everything IXL returns, so the extractor can be tuned by eye."""

    async def run() -> int:
        config = load_config(args.config)
        provider = IXLProvider(config)
        out = Path(args.out)
        try:
            result = await provider.probe(args.kid, out)
        except Exception as exc:  # noqa: BLE001
            print(f"Probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            await provider.close()
        for line in result.diagnostics:
            print(f"  - {line}")
        print(f"\n{len(result.lessons)} lesson(s) matched:")
        for lesson in result.lessons:
            print(f"  {lesson.day}  {lesson.describe()}   ref={lesson.ref}")
        if not result.lessons:
            print(
                "\nNothing matched. Open the JSON in "
                f"{out} and look for the objects that describe finished skills, "
                "then widen the key lists in providers/ixl_extract.py."
            )
        return 0

    return asyncio.run(run())


def cmd_sync(args: argparse.Namespace) -> int:
    async def run() -> int:
        config = load_config(args.config)
        known = [k.id for k in config.kids]
        if args.kid and args.kid not in known:
            print(
                f"No kid called {args.kid!r}. Configured: {', '.join(known)}",
                file=sys.stderr,
            )
            return 1
        engine = _engine(config)
        targets = [args.kid] if args.kid else known
        failures = 0
        for kid_id in targets:
            report = await engine.sync_kid(kid_id, reason="cli")
            flag = "ok " if report.ok else "FAIL"
            print(
                f"[{flag}] {kid_id}: +{report.minutes_earned}m earned, "
                f"-{report.minutes_consumed}m played, balance {report.balance}m, "
                f"limit -> {report.target_limit}"
            )
            for message in report.messages:
                print(f"        {message}")
            failures += 0 if report.ok else 1
        for closable in (engine.provider, engine.switch):
            closer = getattr(closable, "close", None)
            if closer:
                await closer()
        return 1 if failures else 0

    return asyncio.run(run())


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    db = Database(config.server.database)
    print(f"{'kid':<12}{'balance':>10}   last sync")
    for kid in config.kids:
        current = balance(db.events_for(kid.id))
        report = db.get_state(f"report:{kid.id}") or {}
        when = report.get("at", "never")
        note = "" if report.get("ok", True) else "  (degraded)"
        print(f"{kid.name:<12}{humanise(current):>10}   {when}{note}")
    return 0


def cmd_check_config(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(
        {
            "kids": [
                {
                    "id": k.id,
                    "name": k.name,
                    "ixl_ready": k.ixl_ready,
                    "switch_ready": k.switch_ready,
                }
                for k in config.kids
            ],
            "ixl_enabled": config.ixl.enabled,
            "nintendo_enabled": config.nintendo.enabled,
            "nintendo_token_present": bool(config.nintendo.session_token),
            "dry_run": config.nintendo.dry_run,
            "minutes_per_lesson": config.rules.minutes_per_lesson,
        },
        indent=2,
    ))
    return 0


# ----- wiring -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="switchtime", description=__doc__)
    parser.add_argument("-c", "--config", default=None, help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)

    login = sub.add_parser("nintendo-login", help="get a Nintendo session token")
    login.set_defaults(func=cmd_nintendo_login)

    devices = sub.add_parser("devices", help="list Switch consoles and their ids")
    devices.set_defaults(func=cmd_devices)

    probe = sub.add_parser("probe", help="dump what IXL returns for one kid")
    probe.add_argument("kid")
    probe.add_argument("--out", default="data/probe")
    probe.set_defaults(func=cmd_probe)

    sync = sub.add_parser("sync", help="run one sync pass now")
    sync.add_argument("kid", nargs="?")
    sync.set_defaults(func=cmd_sync)

    status = sub.add_parser("status", help="show balances")
    status.set_defaults(func=cmd_status)

    check = sub.add_parser("check-config", help="validate config.toml and show what is wired up")
    check.set_defaults(func=cmd_check_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
