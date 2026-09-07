"""Command line entry points: setup, diagnostics and running the server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


def oauth_state(url: str) -> str | None:
    """Pull the OAuth `state` out of an authorize URL or the redirect it produces.

    The authorize URL carries it in the query string and the npf... redirect
    carries it in the fragment, so both are checked.
    """
    parsed = urlparse(url.strip())
    for blob in (parsed.query, parsed.fragment):
        if not blob:
            continue
        values = parse_qs(blob).get("state")
        if values and values[0]:
            return values[0]
    return None


def _env_local_path(config_path: str | None) -> Path:
    """Where secrets live: beside config.toml, so both travel together."""
    base = Path(config_path).resolve().parent if config_path else Path.cwd()
    return base / ".env.local"


def _store_secret(env_path: Path, key: str, value: str) -> None:
    """Write KEY=value into .env.local, replacing any existing line for KEY.

    Creating the file restricted before writing to it avoids a window where the
    secret exists world-readable.
    """
    line = f"{key}={value}"
    if env_path.exists():
        kept = [
            existing
            for existing in env_path.read_text(encoding="utf-8").splitlines()
            if not existing.startswith(f"{key}=")
        ]
        body = "\n".join([*kept, line]).strip() + "\n"
    else:
        env_path.touch(mode=0o600)
        body = (
            "# Read by the background service. Keep this file private.\n"
            f"{line}\n"
        )
    env_path.chmod(0o600)
    env_path.write_text(body, encoding="utf-8")
    env_path.chmod(0o600)


def cmd_nintendo_login(args: argparse.Namespace) -> int:
    """Walk through Nintendo's OAuth flow once and save a reusable token."""

    async def run() -> int:
        import aiohttp
        from pynintendoparental import Authenticator

        async with aiohttp.ClientSession() as session:
            auth = Authenticator(client_session=session)
            expected = oauth_state(auth.login_url)
            print("\n1. Open this URL in a browser signed in as the parent account.")
            print("   Close any Nintendo sign-in tab left from an earlier attempt first:")
            print("   each run makes a new secret, and only this run's URL can finish it.\n")
            print(f"   {auth.login_url}\n")
            print("2. Sign in. You land on a 'Link an account' page with a red")
            print("   'Select this account' button.\n")
            print("3. RIGHT-CLICK that button and choose 'Copy link address'.")
            print("   On a Chromebook, right-click is a two-finger tap or Alt+click.")
            print("   Do not left-click it: that navigates to npf...://auth, which the")
            print("   browser cannot open, and the code goes with it.\n")
            print("   No 'Copy link address' in the menu? Press Ctrl+Shift+J and run:")
            print("     document.querySelector('a[href^=\"npf\"]').href\n")

            for attempt in range(3):
                redirect = input("Pasted URL: ").strip()
                if not redirect:
                    print("Nothing pasted — aborting.", file=sys.stderr)
                    return 1
                if not redirect.startswith("npf"):
                    print(
                        "\nThat does not look like the redirect — it should start with 'npf'.\n"
                        "Right-click the red 'Select this account' button and choose\n"
                        "'Copy link address', rather than copying the address bar.\n",
                        file=sys.stderr,
                    )
                    continue
                # Catch the common mistake before Nintendo answers with an opaque
                # 400: a redirect belonging to some other sign-in attempt, whose
                # secret this run does not hold.
                supplied = oauth_state(redirect)
                if expected and supplied and supplied != expected:
                    print(
                        "\nThat redirect is from a different sign-in attempt, so the secret\n"
                        "it was issued against is not the one this run is holding.\n"
                        "Open the URL printed above — that exact one — finish the sign-in\n"
                        "there, and paste the redirect it gives you.\n",
                        file=sys.stderr,
                    )
                    continue
                try:
                    await auth.async_complete_login(redirect)
                except Exception as exc:  # noqa: BLE001 - surfaced to the operator
                    detail = f"{type(exc).__name__}: {exc}"
                    print(f"\nLogin failed: {detail}", file=sys.stderr)
                    if "invalid" in detail.lower() and attempt < 2:
                        print(
                            "Those codes last about ten minutes. Re-open the URL above for\n"
                            "a fresh one and paste again.\n",
                            file=sys.stderr,
                        )
                        continue
                    return 1
                token = auth.session_token or ""
                if args.print_token:
                    print("\nSession token:\n")
                    print(f"   {token}\n")
                    print("Treat it like a password — it is valid for years.\n")
                    return 0
                env_path = _env_local_path(args.config)
                try:
                    _store_secret(env_path, "NINTENDO_SESSION_TOKEN", token)
                except OSError as exc:
                    print(f"\nCould not write {env_path}: {exc}", file=sys.stderr)
                    print("Re-run with --print-token to get it on screen instead.", file=sys.stderr)
                    return 1
                # Deliberately not printed in full: it is valid for years, and a
                # token on screen ends up pasted into a chat or a screenshot.
                print(f"\nSaved to {env_path} (mode 600).")
                print(f"Token starts {token[:12]}… and is valid for years — treat it as a password.")
                print("\nNext: switchtime devices\n")
                return 0

            print("Too many attempts — run the command again.", file=sys.stderr)
            return 1

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
        print(f"{len(devices)} console(s) on this account:\n")
        for device in devices:
            # The label is whatever the console is called in the Parental
            # Controls app, and is the only thing that says whose it is.
            label = device["name"] or "(no nickname set)"
            limit = device["limit"]
            limit_text = "not set" if limit in (None, -1) else f"{limit} min"
            print(f"  {label}")
            print(f"      switch_device_id = \"{device['device_id']}\"")
            print(f"      model              {device['model'] or 'unknown'}")
            print(f"      played today       {device['played_today']} min")
            print(f"      daily limit        {limit_text}")
            print()
        print("Put the right id in each [[kids]] block in config.toml.")
        print("Nicknames come from the Parental Controls app; rename a console")
        print("there if they are not obvious.\n")
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
        print("\nWhat happened:")
        for line in result.diagnostics:
            print(f"  - {line}")

        print(f"\n{len(result.lessons)} lesson(s) matched:")
        for lesson in result.lessons:
            print(f"  {lesson.day}  {lesson.describe()}   ref={lesson.ref}")

        saved = sorted(out.glob(f"{args.kid}-*"))
        if saved:
            print(f"\nSaved to {out}/ :")
            for item in saved:
                print(f"  {item.name}  ({item.stat().st_size // 1024} KB)")

        if not result.lessons:
            print(
                "\nNothing matched. Work through these in order:\n"
                "  1. Open the *-1-after-signin.png screenshot. If it shows a login\n"
                "     page, the sign-in failed — check the username and password.\n"
                "  2. Open the *-report.png screenshots. If they are the wrong pages,\n"
                "     fix report_urls in config.toml.\n"
                "  3. If the reports look right but nothing matched, lower\n"
                "     min_smartscore (0 counts any skill practised at all).\n"
                "  4. If it is still empty, the skills are in the dumped JSON under\n"
                "     key names the extractor does not know. Search the .json for a\n"
                "     skill name you can see in the screenshot, then add its keys to\n"
                "     switchtime/providers/ixl_extract.py."
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


def cmd_grant(args: argparse.Namespace) -> int:
    """Add or remove minutes by hand. Useful for testing, and for a one-off."""
    config = load_config(args.config)
    known = [k.id for k in config.kids]
    if args.kid not in known:
        print(f"No kid called {args.kid!r}. Configured: {', '.join(known)}", file=sys.stderr)
        return 1
    db = Database(config.server.database)
    engine = SyncEngine(config, db, FakeProvider(), NullSwitchClient())
    engine.adjust(args.kid, args.minutes, args.note or "Granted from the command line")
    current = balance(db.events_for(args.kid))
    verb = "Added" if args.minutes >= 0 else "Removed"
    print(f"{verb} {humanise(abs(args.minutes))} for {config.kid(args.kid).name}.")
    print(f"Balance is now {humanise(current)}.")
    print(f"\nRun `switchtime sync {args.kid}` to push it to the console.")
    return 0


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
    print(f"IXL          {'on' if config.ixl.enabled else 'off'}  ({config.ixl.base_url})")
    print(f"Nintendo     {'on' if config.nintendo.enabled else 'off'}"
          f"{'  DRY RUN — nothing reaches a console' if config.nintendo.dry_run else ''}")
    print(f"Minutes/lesson {config.rules.minutes_per_lesson}\n")

    problems = missing_secrets(config)
    for kid in config.kids:
        marks = []
        marks.append("IXL ok" if kid.ixl_ready else "IXL not ready")
        marks.append("console ok" if kid.switch_ready else "no console")
        print(f"  {kid.name:<10} {' · '.join(marks)}")
    print()

    if not config.nintendo.session_token and config.nintendo.enabled:
        problems.append("No Nintendo session token — run `switchtime nintendo-login`.")
    if problems:
        print("Needs attention:")
        for line in problems:
            print(f"  - {line}")
        return 1
    print("Everything needed is configured.")
    return 0


def missing_secret_vars(config: Config) -> list[tuple[str, str]]:
    """(who it is for, variable name) for every declared but empty secret."""
    out: list[tuple[str, str]] = []
    if not config.ixl.enabled:
        return out
    for kid in config.kids:
        if kid.ixl_username and not kid.ixl_password:
            out.append((kid.name, kid.ixl_password_env_name or "ixl_password_env"))
        if kid.ixl_profile and not kid.ixl_profile_password:
            out.append(
                (f"{kid.name} (profile)", kid.ixl_profile_password_env_name or "ixl_profile_password_env")
            )
    return out


def cmd_set_secret(args: argparse.Namespace) -> int:
    """Prompt for a secret and write it to .env.local without echoing it."""
    import getpass

    config = load_config(args.config)
    env_path = _env_local_path(args.config)
    targets = [args.name] if args.name else [name for _, name in missing_secret_vars(config)]
    if not targets:
        print("Nothing missing — every declared secret already has a value.")
        return 0

    for name in targets:
        try:
            value = getpass.getpass(f"Value for {name} (typing is hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1
        if not value:
            print(f"Nothing entered for {name}, skipping.", file=sys.stderr)
            continue
        _store_secret(env_path, name, value)
        print(f"  {name} saved to {env_path} ({len(value)} characters)")

    print("\nRun `switchtime check-config` to confirm.")
    return 0


def missing_secrets(config: Config) -> list[str]:
    """Name the environment variables that are declared but empty.

    An unset password is otherwise indistinguishable from a wrong one once a
    browser is involved, so it is worth catching before anything launches.
    """
    problems = [
        f"{who}: {name} is unset in .env.local — run `switchtime set-secret {name}`"
        for who, name in missing_secret_vars(config)
    ]
    problems += [
        f"{kid.name}: a password is set but ixl_username is missing."
        for kid in config.kids
        if kid.ixl_password and not kid.ixl_username
    ]
    return problems


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
    login.add_argument(
        "--print-token",
        action="store_true",
        help="print the token instead of saving it to .env.local (for Docker or a password manager)",
    )
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

    grant = sub.add_parser("grant", help="add or remove minutes by hand")
    grant.add_argument("kid")
    grant.add_argument("minutes", type=int, help="negative to take time away")
    grant.add_argument("--note", default="")
    grant.set_defaults(func=cmd_grant)

    secret = sub.add_parser(
        "set-secret", help="store a password in .env.local without echoing it"
    )
    secret.add_argument("name", nargs="?", help="variable name; omit to fill in every missing one")
    secret.set_defaults(func=cmd_set_secret)

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
