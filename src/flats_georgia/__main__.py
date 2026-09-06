"""CLI entry point: ``python -m flats_georgia [--dry-run] [--force-full] [--always-send]``."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import sys

from flats_georgia.config import load_settings
from flats_georgia.pipeline import run


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252 and choke on the digest's emoji."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            with contextlib.suppress(ValueError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flats_georgia",
        description="Send a Telegram digest of new MyHome.ge rentals matching the fixed filter.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the digest, send nothing, touch no state"
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="treat every current listing as new (re-send the whole filter)",
    )
    parser.add_argument(
        "--always-send",
        action="store_true",
        help="send a message even when there is nothing new",
    )
    args = parser.parse_args(argv)

    _force_utf8_stdout()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings(require_secrets=not args.dry_run)
    return run(
        settings,
        dry_run=args.dry_run,
        force_full=args.force_full,
        always_send=args.always_send,
    )


if __name__ == "__main__":
    sys.exit(main())
