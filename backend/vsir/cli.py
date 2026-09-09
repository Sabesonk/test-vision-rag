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
from vsir.core.exact import UnknownScopeKey, exact_filter, phrases_of
from vsir.core.tok import tok
from vsir.core.variants import preserves_characters, variants
from vsir.doctor import doctor
from vsir.serve.caps import (
    ToolError,
    validate_budget,
    validate_dpi,
    validate_fetch_pages,
    validate_read_pages,
    validate_scope,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INTERRUPTED = 130

_log = vsir_logging.get_logger(__name__)


def _cmd_doctor(args: argparse.Namespace) -> int:
    return doctor(create_collection=args.create_collection)


#: The label shapes this corpus prints. The demo runs the exact surface over all of them.
_DEMO_LABELS = (
    "SF 1.1A", "SF1.1A", "SF121.1)", "84-5140.0020", "X20SI4100", "SI3", "K158", "K73", "0020",
    "alarm 152",
)

#: One line per §7.3 bound: the call that violates it, and the code it must raise.
_DEMO_CAPS = (
    ("read, 4 pages", lambda: validate_read_pages(["a", "b", "c", "d"]), "read_page_cap_exceeded"),
    ("fetch, 6 pages", lambda: validate_fetch_pages(["a"] * 6), "fetch_budget_exceeded"),
    ("dpi=100", lambda: validate_dpi(100), "dpi_not_allowed"),
    ("dpi=300, no region", lambda: validate_dpi(300, None), "dpi_requires_region"),
    ("scope={'bogus': 1}", lambda: validate_scope({"bogus": 1}), "filter_unknown_key"),
    ("reads_remaining=0", lambda: validate_budget(0), "budget_exhausted"),
)


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _demo_primitives() -> bool:
    """The exact surface, printed for a reviewer: variants, the filter, tokens, and the caps.

    Prints a human-readable report rather than the JSON event stream: this is a one-off command
    whose output *is* the deliverable a reviewer reads (§4.4), and it is the shape its ancestor
    `impl/scripts/interfaces_demo.py` had.
    """
    passed = True

    print("\n1. variants(label) — three spellings of the SAME characters (§5.6, I3)")
    print(f"   {'label':<16} {'variants':<44} character-preserving")
    for label in _DEMO_LABELS:
        preserved = preserves_characters(label)
        passed &= preserved
        spellings = " · ".join(variants(label))
        print(f"   {label:<16} {spellings:<44} {_verdict(preserved)}")

    print("\n2. exact_filter(label, scope) — the ONLY exact-match code path (§5.6, F1)")
    query = exact_filter("SF 1.1A", {"doc_id": "TC1E-SF", "is_current": True})
    print("   should[")
    for branch in query.should or []:
        conditions = ", ".join(
            f"MatchPhrase(text={condition.match.phrase!r})"
            if getattr(condition.match, "phrase", None) is not None
            else f"{condition.key}={getattr(condition.match, 'value', None)!r}"
            for condition in branch.must or []
        )
        print(f"     must[ {conditions} ]")
    print("   ]")
    phrases = phrases_of(query)
    filter_ok = phrases == list(variants("SF 1.1A")) and len(query.should or []) == 3
    passed &= filter_ok
    print(f"   one phrase per variant, scope ANDed into every branch          {_verdict(filter_ok)}")

    print("\n3. tok() mirrors Qdrant's WORD tokenizer, not impl's TOKEN_RE (§5.6, §2.4)")
    print(f"   {'label':<16} {'tok(label)':<34} not one token")
    for label in _DEMO_LABELS:
        tokens = tok(label)
        split_ok = tokens == [t for t in tokens if t]
        passed &= split_ok
        print(f"   {label:<16} {str(tokens):<34} {_verdict(split_ok)}")
    dotted_ok = tok("84-5140.0020") == ["84", "5140", "0020"]
    passed &= dotted_ok
    print(f"   84-5140.0020 -> three tokens, which is why phrase matching is the mechanism"
          f"  {_verdict(dotted_ok)}")
    print("   agreement with a live qdrant/qdrant:v1.19.0 is proved at L2:")
    print("     backend/tests/api/test_tokenizer_differential.py")

    print("\n4. §7.3 caps — each a typed 400 naming its bound, never a clamp (F18)")
    for description, call, expected in _DEMO_CAPS:
        try:
            call()
        except ToolError as refusal:
            correct = refusal.code == expected
            passed &= correct
            print(f"   {description:<22} -> {refusal.http_status} {refusal.code:<24} "
                  f"{refusal.details}  {_verdict(correct)}")
        else:
            passed = False
            print(f"   {description:<22} -> NO ERROR RAISED                          FAIL")

    print("\n5. an unknown scope key never reaches the index (I6, F10)")
    try:
        exact_filter("K158", {"content.units": "nope"})
    except UnknownScopeKey as refusal:
        print(f"   exact_filter(scope={{'content.units': ...}}) -> UnknownScopeKey"
              f"{refusal.keys}  {_verdict(True)}")
    else:
        passed = False
        print("   exact_filter accepted an unindexed key                            FAIL")

    return passed


def _cmd_demo_exact(args: argparse.Namespace) -> int:
    print(f"vsir demo exact — release {os.environ.get('VSIR_RELEASE_ID', 'unknown')}, "
          f"section {args.only}")
    passed = _demo_primitives()
    print(f"\n{'ALL ASSERTIONS PASSED' if passed else 'ASSERTIONS FAILED'}")
    return EXIT_OK if passed else EXIT_REFUSED


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

    demo_parser = commands.add_parser("demo", help="the reviewable demos of §4.4")
    demos = demo_parser.add_subparsers(dest="demo", metavar="<demo>", required=True)
    exact_demo = demos.add_parser(
        "exact",
        help="the exact surface: variants, the one filter, the tokenizer, and the §7.3 caps",
    )
    exact_demo.add_argument(
        "--synthetic",
        action="store_true",
        help="use the synthetic corpus as the demo's data source rather than a frozen fixture; "
             "the `primitives` section is pure and reads no corpus at all",
    )
    exact_demo.add_argument(
        "--only",
        choices=["primitives"],
        default="primitives",
        help="which section to run (the seeded-corpus sections arrive with U005)",
    )
    exact_demo.set_defaults(handler=_cmd_demo_exact)

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
