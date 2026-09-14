"""Command line: import history, see the list, run the server, send a reminder."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from . import ingest as ingest_module
from . import mailbox as mailbox_module
from . import notify, suggest
from .config import Config, ConfigError, load_config
from .db import Database
from .importers import CsvImporter, EmailImporter, FakeImporter, ImportError_, detect
from .importers.csv_import import parse_date

IMPORTERS = [EmailImporter(), CsvImporter()]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _store(config: Config) -> Database:
    return Database(config.server.database)


# ----- commands ---------------------------------------------------------


def cmd_serve(args: argparse.Namespace, config: Config) -> int:
    import uvicorn

    from .app import build_app

    uvicorn.run(
        build_app(config),
        host=args.host or config.server.host,
        port=args.port or config.server.port,
        log_level="debug" if args.verbose else "info",
    )
    return 0


def cmd_import(args: argparse.Namespace, config: Config) -> int:
    db = _store(config)
    paths: list[Path] = []
    for raw in args.paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            paths.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        else:
            paths.append(path)

    if not paths:
        print("nothing to import", file=sys.stderr)
        return 1

    total = ingest_module.IngestResult()
    for path in paths:
        try:
            importer = detect(path, IMPORTERS)
        except ImportError_ as exc:
            if args.verbose:
                print(f"skip {path.name}: {exc}", file=sys.stderr)
            continue
        if args.show_text and isinstance(importer, EmailImporter):
            print(f"----- {path.name} as the parser sees it -----")
            print(importer.flatten(path))
            print("-" * 50)
        try:
            orders = importer.read(path)
        except (ImportError_, OSError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            continue

        result = ingest_module.ingest(db, orders, config, dry_run=args.dry_run, force=args.force)
        print(f"{path.name}: {result.summary()}")
        if args.dry_run or args.verbose:
            for match in result.matches:
                print(f"    {match.quantity:>4g}  {match.raw_name[:52]:54} -> {match.item_name} [{match.how}]")
        total.orders += result.orders
        total.lines += result.lines
        total.added += result.added
        total.duplicates += result.duplicates
        total.skipped_orders += result.skipped_orders
        total.new_items.extend(result.new_items)

    print(f"\n{'would import' if args.dry_run else 'imported'}: {total.summary()}")
    if total.new_items:
        print("new items: " + ", ".join(sorted(set(total.new_items))))
    if args.dry_run:
        print("\nNothing was written. Re-run without --dry-run to keep it.")
    return 0


def cmd_suggest(args: argparse.Namespace, config: Config) -> int:
    report = suggest.build(_store(config), config)
    if report is None:
        print("no delivery slots configured; add a [[slots]] entry", file=sys.stderr)
        return 1
    print(suggest.render_text(report))
    if report.unsure and args.verbose:
        print("\nnot enough history to call:")
        for est in report.unsure:
            print(f"  {est.item.name} ({est.purchases} purchase(s))")
    return 0


def cmd_items(args: argparse.Namespace, config: Config) -> int:
    db = _store(config)
    today = date.today()
    rows = suggest.estimates(db, config, today)
    if not rows:
        print("no items yet; run `trolley import` or `trolley demo`")
        return 0
    rows.sort(key=lambda e: (e.due_on or date.max, e.item.name))
    print(f"{'item':26} {'bought':>7} {'every':>7} {'last':>11} {'due':>11}  conf  basis")
    for est in rows:
        every = f"{est.interval:.0f}d" if est.interval else "-"
        print(
            f"{est.item.name[:26]:26} {est.purchases:>7} {every:>7} "
            f"{str(est.last_bought or '-'):>11} {str(est.due_on or '-'):>11} "
            f"{est.confidence:5.2f}  {est.basis}"
            + ("  (paused)" if est.item.paused else "")
        )
    return 0


def cmd_add(args: argparse.Namespace, config: Config) -> int:
    db = _store(config)
    from . import normalise

    key, name, _ = normalise.resolve(args.item, tuple(i.key for i in db.items()), config.aliases)
    item = db.item_by_key(key) or db.upsert_item(key, name, normalise.category_of(key))
    when = parse_date(args.date) if args.date else date.today()
    if when is None:
        print(f"could not read date {args.date!r}", file=sys.stderr)
        return 1
    db.add_purchase(item.id, when, args.quantity, args.item, None, "manual")
    print(f"recorded {args.quantity:g} x {item.name} on {when}")
    return 0


def cmd_link(args: argparse.Namespace, config: Config) -> int:
    print(ingest_module.relink(_store(config), args.raw_name, args.item_key))
    return 0


def cmd_notify(args: argparse.Namespace, config: Config) -> int:
    report = suggest.build(_store(config), config)
    if report is None:
        print("no delivery slots configured", file=sys.stderr)
        return 1
    if not report.suggestions and not args.force:
        print("nothing due; not sending")
        return 0
    body = suggest.render_text(report)
    try:
        notify.send(config.notify, f"Trolley: {report.slot.label}", body)
    except notify.NotifyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_setup_mail(args: argparse.Namespace, config: Config) -> int:
    """Ask for the mailbox details, prove they work, then write them down."""
    from dataclasses import replace

    from . import setup_mail

    # Anything given on the command line becomes the offered default, which is
    # what makes this scriptable for a container or a second machine.
    given = {
        name: value
        for name, value in (
            ("username", args.username),
            ("host", args.host),
            ("port", args.port),
            ("folder", args.folder),
            ("search", args.search),
            ("security", args.security),
        )
        if value
    }
    defaults = replace(config.mailbox, **given) if given else config.mailbox
    path = Path(args.config).expanduser() if args.config else Path("config.toml")
    return setup_mail.run(
        config,
        path,
        _store(config),
        defaults=defaults,
        given=frozenset(given),
    )


def cmd_mail(args: argparse.Namespace, config: Config) -> int:
    """Read order emails from the configured mailbox."""
    if not config.mailbox.enabled:
        print(
            "[mailbox] is not enabled. Add a [mailbox] section to your config "
            "(see config.example.toml) and set TROLLEY_IMAP_PASSWORD.",
            file=sys.stderr,
        )
        return 1

    box = mailbox_module.Mailbox(config.mailbox)
    db = _store(config)
    try:
        if args.test:
            print(box.check())
            return 0
        if args.reset:
            mailbox_module.reset_position(db)
            print("forgot where it got to; the next read starts from the beginning")

        runner = mailbox_module.collect_all if args.all else mailbox_module.collect
        result = runner(db, config, mailbox=box, dry_run=args.dry_run)
    except mailbox_module.MailboxError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(result.summary())
    if result.reset:
        print("(the mailbox was renumbered by the server, so it was re-read)")
    if args.dry_run or args.verbose:
        for match in result.ingest.matches:
            print(f"    {match.quantity:>4g}  {match.raw_name[:52]:54} -> {match.item_name} [{match.how}]")
    if args.dry_run:
        print("\nNothing was written. Re-run without --dry-run to keep it.")
    return 0


def cmd_demo(args: argparse.Namespace, config: Config) -> int:
    db = _store(config)
    orders = FakeImporter().generate(weeks=args.weeks)
    result = ingest_module.ingest(db, orders, config)
    print(f"demo history loaded: {result.summary()}")
    print("\nnow try: trolley suggest")
    return 0


# ----- wiring -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trolley",
        description="Suggests what to add to the next Tesco order, from what you usually buy.",
    )
    parser.add_argument("-c", "--config", help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the web app")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)

    importer = subparsers.add_parser(
        "import", help="read order confirmation emails, HTML or CSV files"
    )
    importer.add_argument("paths", nargs="+", help="files or directories")
    importer.add_argument("--dry-run", action="store_true", help="show what would be imported")
    importer.add_argument("--show-text", action="store_true", help="print the flattened email")
    importer.add_argument("--force", action="store_true", help="re-read orders already imported")
    importer.set_defaults(func=cmd_import)

    suggest_cmd = subparsers.add_parser("suggest", help="print the list for the next delivery")
    suggest_cmd.set_defaults(func=cmd_suggest)

    items = subparsers.add_parser("items", help="show every item and when it is next due")
    items.set_defaults(func=cmd_items)

    add = subparsers.add_parser("add", help="record a purchase by hand")
    add.add_argument("item", help="product or item name")
    add.add_argument("--date", help="when, e.g. 2026-09-14 or 14/09/2026 (default today)")
    add.add_argument("--quantity", type=float, default=1.0)
    add.set_defaults(func=cmd_add)

    link = subparsers.add_parser("link", help="make a product name count as a given item")
    link.add_argument("raw_name", help='the product name as it appears on receipts')
    link.add_argument("item_key", help='the item key, e.g. "toilet-roll"')
    link.set_defaults(func=cmd_link)

    setup = subparsers.add_parser(
        "setup-mail", help="connect a mailbox, test it, and save the settings"
    )
    setup.add_argument("--username", help="email address (otherwise you are asked)")
    setup.add_argument("--host", help="IMAP host (otherwise guessed from the address)")
    setup.add_argument("--port", type=int, help="IMAP port (default 993)")
    setup.add_argument("--folder", help="folder or Gmail label to read")
    setup.add_argument("--search", help='IMAP search, default FROM "tesco"')
    setup.add_argument(
        "--security", choices=("ssl", "starttls", "none"),
        help="ssl for port 993, starttls for 143, none for a local bridge",
    )
    setup.set_defaults(func=cmd_setup_mail)

    mail = subparsers.add_parser("mail", help="read order emails from the configured mailbox")
    mail.add_argument("--test", action="store_true", help="check the settings without importing")
    mail.add_argument("--dry-run", action="store_true", help="show what would be imported")
    mail.add_argument("--all", action="store_true", help="keep going until the mailbox is caught up")
    mail.add_argument("--reset", action="store_true", help="re-read from the beginning")
    mail.set_defaults(func=cmd_mail)

    notify_cmd = subparsers.add_parser("notify", help="send the reminder now")
    notify_cmd.add_argument("--force", action="store_true", help="send even if nothing is due")
    notify_cmd.set_defaults(func=cmd_notify)

    demo = subparsers.add_parser("demo", help="load a year of invented history to try it out")
    demo.add_argument("--weeks", type=int, default=52)
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return args.func(args, config)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
