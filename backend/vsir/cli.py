"""The ``vsir`` CLI — the only supported operational surface (Spec §4.4, §15 Factor XII).

Ported from ``impl/scripts/interfaces_demo.py``: the argparse spine and its one-shot,
print-what-you-did style survive. What does not survive is that script's shape — five hard-coded
interface calls in one ``main()``. Here each command of §4.4 is a subparser registered by the
milestone that implements it, because an operational action that cannot be expressed as a ``vsir``
subcommand is not a supported operation (§15 Factor XII). ``doctor`` is the only one at M0.

Every command returns an exit code and logs JSON events to stdout (§15 Factor XI). A refusal is a
non-zero exit with a named reason — never a warning followed by a partial success (§4.3).
"""
from __future__ import annotations

import argparse
import os
import signal
from types import FrameType
from typing import Any

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.doctor import doctor

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INTERRUPTED = 130

_log = vsir_logging.get_logger(__name__)


def _cmd_doctor(args: argparse.Namespace) -> int:
    return doctor(create_collection=args.create_collection)


def build_parser() -> argparse.ArgumentParser:
    """The command table of Spec §4.4, as far as it has been built."""
    parser = argparse.ArgumentParser(
        prog="vsir",
        description="Vision segmentation, index and retrieval — the operational surface (§4.4).",
    )
    parser.add_argument("--version", action="version", version=f"vsir {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    doctor_parser = commands.add_parser(
        "doctor",
        help="run the boot self-check (§4.3): prints release_id, the resolved model ids and the "
             "index fingerprint, and refuses a floating model alias or a missing variable",
    )
    doctor_parser.add_argument(
        "--create-collection",
        action="store_true",
        help="create the vsir_pages collection from INDEXED first, then assert the live schema "
             "back against it (§5.5) — a one-off admin process, not live surgery",
    )
    doctor_parser.set_defaults(handler=_cmd_doctor)

    return parser


def install_sigterm_handler() -> None:
    """Exit cleanly on ``SIGTERM`` (§15 Factor IX).

    At M0 there is nothing in flight to drain, so the honest handler is: say so on the event
    stream, and exit 0 immediately. The server's drain and the ingest window checkpoint attach to
    this same signal in U014 and U025 — a kill must lose at most one window and must never publish
    a partial run (I7, F17).
    """

    def _on_sigterm(signum: int, _frame: FrameType | None) -> None:
        _log.info("sigterm", signal=signum, action="exit", draining=0)
        raise SystemExit(EXIT_OK)

    signal.signal(signal.SIGTERM, _on_sigterm)


def main(argv: list[str] | None = None) -> int:
    """Parse, configure logging, install the signal handler, run one command."""
    args = build_parser().parse_args(argv)

    # Logging is configured from the raw environment, before any check runs: the boot self-check
    # reports a missing or malformed VSIR_LOG_LEVEL, and it needs a working logger to report with.
    vsir_logging.configure(
        release_id=(os.environ.get("VSIR_RELEASE_ID") or "").strip() or "unknown",
        level=(os.environ.get("VSIR_LOG_LEVEL") or "INFO").strip(),
    )
    install_sigterm_handler()

    handler: Any = args.handler
    try:
        return handler(args)
    except KeyboardInterrupt:
        _log.warning("interrupted", command=args.command, action="exit")
        return EXIT_INTERRUPTED
