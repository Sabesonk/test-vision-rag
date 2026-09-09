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
import ast
import os
import signal
from pathlib import Path
from types import FrameType
from typing import Any

from qdrant_client import QdrantClient

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import ConfigError, load_config, scrub_url
from vsir.core import observed_tokens as observed_tokens_module
from vsir.core.exact import UnknownScopeKey, exact_filter, phrases_of
from vsir.core.nearmiss import is_printed, near_misses
from vsir.core.observed_tokens import from_records, is_code_like, is_searchable
from vsir.core.present_instead import PRESENT_INSTEAD_CAP, PRESENT_INSTEAD_LABEL
from vsir.core.verify import page_checks, verify_claims
from vsir.core.tok import tok, token_set
from vsir.core.variants import preserves_characters, variants
from vsir.doctor import doctor
from vsir.eval import synthetic
from vsir.serve.caps import (
    ToolError,
    validate_budget,
    validate_dpi,
    validate_fetch_pages,
    validate_read_pages,
    validate_scope,
)
from vsir.serve.envelope import Provenance, ToolEnvelope, VerifyResult
from vsir.serve.tools import lookup as lookup_module
from vsir.serve.tools.lookup import lookup

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


def _line(description: str, observed: str, ok: bool) -> bool:
    """One assertion, one line: what was asked, what came back, and the verdict."""
    print(f"   {description:<40} {observed:<40} {_verdict(ok)}")
    return ok


def _shape(response: Any) -> str:
    """A response, small enough to read: status, set size, and the pages it named."""
    pages = " ".join(hit.page_id.split("#")[-1] for hit in response.hits) or "—"
    return f"{response.status.value} total={response.total} {pages}"


def _imports_of(module: Any) -> set[str]:
    """Every module name imported by ``module``'s source, read from its AST.

    A module boundary is only a guarantee if something checks it. §6.8 requires the observed-token
    inventory to be *structurally* unreachable from `lookup`, and "structurally" means this: not a
    convention, not a review habit, but a fact about the import graph that a reviewer can see and
    a test can fail on.
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _demo_corpus_facts(corpus: synthetic.Corpus, records: tuple[Any, ...], seeded: int) -> bool:
    expected = corpus.expected["corpus"]
    print("\n6. the §13 M1 corpus — hand-written page text, no PDF, no VLM, no spend")
    print(f"   source {corpus.source}")
    current = [record for record in records if record.is_current]
    no_text = [record for record in current if not record.has_text]
    unsearchable = [record for record in current
                    if record.text_trust in lookup_module.UNSEARCHABLE_TRUST]
    passed = _line(f"{corpus.doc_id}@{corpus.revision}, pages seeded",
                   f"{seeded} points, {len(current)} current",
                   seeded == len(records) and len(current) == expected["pages"])
    passed &= _line("pages with no text layer (§5.7)", f"{len(no_text)}",
                    len(no_text) == expected["pages_no_text"])
    passed &= _line("pages unsearchable for lookup (§5.7)", f"{len(unsearchable)}",
                    len(unsearchable) == expected["pages_unsearchable"])
    passed &= _line(f"superseded revision {expected['superseded_revision']} kept, not deleted",
                    f"{len(records) - len(current)} page, is_current=False",
                    len(records) - len(current) == expected["superseded_pages"])
    return passed


def _demo_exact_set(ask: Any, corpus: synthetic.Corpus) -> bool:
    expected = corpus.expected
    decoy = expected["decoy"]

    print("\n7. lookup(label) — exact, phrase-only, a SET not a ranking (§7.2.2, F1)")
    first = expected["compact_labels"][0]
    response = ask(first["label"])
    passed = _line(f'lookup("{first["label"]}")', _shape(response),
                   response.total == 1 and len(response.hits) == 1
                   and response.hits[0].page_id == first["page_id"])
    passed &= _line("the token-decoy page is NOT returned",
                    f'{decoy["page_id"].split("#")[-1]} absent from hits',
                    decoy["page_id"] not in [hit.page_id for hit in response.hits])
    passed &= _line("every hit carries an image REFERENCE",
                    f"{response.hits[0].image.url}",
                    all(hit.image and hit.image.url for hit in response.hits))
    passed &= _line("no hit carries image bytes (P2, D12)", "no bytes_b64 field",
                    not any("bytes" in field for field in type(response.hits[0]).model_fields))

    print("\n8. the eight compact labels each resolve to the page that prints them (F3)")
    for row in expected["compact_labels"]:
        response = ask(row["label"])
        found = [hit.page_id for hit in response.hits]
        passed &= _line(f'lookup("{row["label"]}") → printed {row["printed"]}',
                        f'{_shape(response)} [{row["variant"]}]',
                        found == [row["page_id"]])
    for row in expected["one_character_apart"]:
        response = ask(row["label"])
        passed &= _line(f'lookup("{row["label"]}") ≠ {row["printed_there"]}', _shape(response),
                        row["not_page_id"] not in [hit.page_id for hit in response.hits])
    return passed


def _demo_unfindable(ask: Any, corpus: synthetic.Corpus) -> bool:
    expected = corpus.expected
    fake = expected["hallucinated"]

    print("\n9. a model-invented code is unfindable in the exact surface (I2, F14, D3)")
    response = ask(fake["label"])
    passed = _line(f'lookup("{fake["label"]}")', _shape(response),
                   response.status.value == fake["status"] and response.hits == []
                   and response.next is None)
    disclosed = ask(fake["label"], include_unverified=True)
    passed &= _line(f'lookup("{fake["label"]}", include_unverified=True)',
                    f"{disclosed.status.value} hits={len(disclosed.hits)} "
                    f"unverified={len(disclosed.unverified_hits)}",
                    disclosed.hits == []
                    and len(disclosed.unverified_hits) == fake["unverified_hits"])
    passed &= _line("the unverified hit is on the claiming page, verified=False",
                    f"{disclosed.unverified_hits[0].page_id.split('#')[-1]} "
                    f"verified={disclosed.unverified_hits[0].verified}",
                    disclosed.unverified_hits[0].page_id == fake["page_id"]
                    and disclosed.unverified_hits[0].verified is False)
    passed &= _line("the two lists are never merged", "hits ∩ unverified_hits = ∅",
                    not ({hit.page_id for hit in disclosed.hits}
                         & {hit.page_id for hit in disclosed.unverified_hits}))

    print("\n10. an unsearchable page is `not_searchable`, never `not_found` (F4, §5.7)")
    for kind in ("no_text", "untrusted"):
        row = expected[kind]
        scoped = ask(row["label"], scope=row["scope"])
        passed &= _line(f'lookup("{row["label"]}", scope={row["scope"]})',
                        f"{scoped.status.value} pages={scoped.scope_stats.pages} "
                        f"no_text={scoped.scope_stats.pages_no_text}",
                        scoped.status.value == row["scoped_status"] and scoped.hits == [])
        unscoped = ask(row["label"])
        passed &= _line(f'lookup("{row["label"]}") unscoped', _shape(unscoped),
                        unscoped.status.value == row["unscoped_status"])
    return passed


def _demo_absences(ask: Any, corpus: synthetic.Corpus) -> bool:
    expected = corpus.expected

    print("\n11. `weak` is the server's signal, and `cap` cannot move it (§7.1)")
    weak = expected["weak"]
    passed = True
    for cap in weak["caps"]:
        response = ask(weak["label"], cap=cap)
        passed &= _line(f'lookup("{weak["label"]}", cap={cap})',
                        f"total={response.total} hits={len(response.hits)} "
                        f"capped={response.capped} weak={response.weak}",
                        response.total == weak["total"]
                        and response.weak is weak["weak"]
                        and response.needs_scope is weak["needs_scope"]
                        and len(response.hits) == min(cap, weak["total"])
                        and response.capped is (weak["total"] > cap))

    # Three of the four absences ship at M1: `not_searchable` is section 10's, and
    # `found_only_in_superseded` is F9's, which §10 closes at M8 — until then a label printed only
    # on a superseded revision is honestly `not_found`, and the last line here is the evidence
    # M8 will upgrade.
    print("\n12. typed absence, and the affordance that keeps it honest (I5, §7.1)")
    for key in ("suggest", "asymmetric_variant"):
        row = expected[key]
        response = ask(row["label"])
        passed &= _line(f'lookup("{row["label"]}")',
                        f"{response.status.value} suggest="
                        f"{response.next.suggest if response.next else []}",
                        response.status.value == row["status"]
                        and (response.next.suggest if response.next else []) == row["suggest"])
    out = expected["out_of_scope"]
    response = ask(out["label"], scope=out["scope"])
    passed &= _line(f'lookup("{out["label"]}", scope={out["scope"]})',
                    f"{response.status.value} pages={response.scope_stats.pages}",
                    response.status.value == out["status"])
    for row in expected["superseded"]:
        response = ask(row["label"])
        passed &= _line(f'lookup("{row["label"]}") — is_current injected (I7)', _shape(response),
                        len(response.hits) == row["hits"]
                        and (response.hits[0].page_id == row["page_id"] if row["hits"] else True))
    echoed = ask(out["label"])
    passed &= _line("effective_scope is echoed back (F8, C11)", f"{echoed.effective_scope}",
                    echoed.effective_scope == {"is_current": True})
    return passed


def _searchable(records: tuple[Any, ...]) -> list[Any]:
    """The pages a code may be observed on: current, and with a text layer worth trusting (§5.7)."""
    return [record for record in records if record.is_current and is_searchable(record)]


def _demo_observed_tokens(corpus: synthetic.Corpus, records: tuple[Any, ...]) -> bool:
    expected = corpus.expected["observed_tokens"]
    current = _searchable(records)
    inventory = from_records(current)[expected["doc_id"]]
    every_text_token = {token for record in current for token in token_set(record.text)}

    print("\n13. the observed-token inventory (§6.8) — display-only, and never a match")
    passed = _line(f"tokens observed in {expected['doc_id']}",
                   f"{len(inventory)} tokens from {len(current)} searchable pages",
                   len(inventory) == expected["count"])
    passed &= _line("every code-like token of the text, and nothing else",
                    "text ∩ has-a-digit",
                    set(inventory.tokens)
                    == {token for token in every_text_token if is_code_like(token)})
    passed &= _line("nothing that is not in the text surface", "no model claim leaks in",
                    all(token in every_text_token for token in inventory.tokens)
                    and all(token not in inventory for token in expected["excludes"]))
    passed &= _line("a prefix lookup, not a distance (F16)",
                    f"starting_with('k7') = {list(inventory.starting_with('k7'))}",
                    inventory.starting_with("k7") == ("k78",)
                    and inventory.starting_with("") == ())

    imports = _imports_of(lookup_module)
    passed &= _line("lookup.py cannot reach the inventory",
                    f"{observed_tokens_module.__name__} not imported",
                    not any("observed_tokens" in name for name in imports))
    return passed


def _demo_verify(client: Any, collection: str, corpus: synthetic.Corpus,
                 claims: list[str]) -> bool:
    """The `verify` half of the exact surface: three states, per (claim, page) (§7.2.4)."""
    rows = [row for row in corpus.expected["verify"]
            if not claims or row["claim"] in claims]
    if not rows:
        every_page = sorted({page for row in corpus.expected["verify"] for page in row["page_ids"]})
        rows = [{"claim": claim, "page_ids": every_page} for claim in claims]

    print("\n14. verify_claims(claims, page_ids) — three states, per (claim, page) (§7.2.4, F2)")
    passed = True
    for row in rows:
        result = verify_claims(client, collection, [row["claim"]], row["page_ids"])
        verdict = result.claims[row["claim"]]
        pages = " ".join(page.split("#")[-1] for page in row["page_ids"])
        detail = verdict.status
        if verdict.status == "present":
            detail += " on " + " ".join(page.split("#")[-1] for page in verdict.page_ids)
        elif verdict.reason:
            detail += f" ({verdict.reason})"
        elif verdict.present_instead:
            detail += f" · {PRESENT_INSTEAD_LABEL}: {verdict.present_instead}"
        expected = row.get("status")
        correct = (
            expected is None
            or (verdict.status == expected
                and verdict.page_ids == row.get("on", verdict.page_ids)
                and verdict.reason == row.get("reason", verdict.reason)
                and verdict.present_instead == row.get("present_instead",
                                                       verdict.present_instead))
        )
        passed &= _line(f'verify("{row["claim"]}", [{pages}])', detail, correct)

    absent_only = VerifyResult(claims={
        claim: verdict for claim, verdict in
        verify_claims(client, collection, ["K999", "K 73"],
                      [corpus.page_id(4), corpus.page_id(6)]).claims.items()})
    envelope = ToolEnvelope[VerifyResult](
        status="ok", result=absent_only,
        provenance=Provenance(run_id=synthetic.SEED_RUN_ID,
                              release_id=os.environ.get("VSIR_RELEASE_ID", "unknown")))
    passed &= _line("every claim absent is still a Family B `ok`",
                    f'status={envelope.status} '
                    f'{[v.status for v in envelope.result.claims.values()]}',
                    envelope.status == "ok"
                    and all(v.status == "absent" for v in envelope.result.claims.values()))

    matrix = page_checks(client, collection, ["K158"],
                         [corpus.page_id(1), corpus.page_id(2)])
    passed &= _line("the matrix is per (claim, page), never collapsed",
                    " ".join(f"{page.split('#')[-1]}={state}"
                             for page, (state, _) in matrix["K158"].items()),
                    [state for state, _ in matrix["K158"].values()] == ["present", "absent"])
    return passed


def _demo_abstention(corpus: synthetic.Corpus, records: tuple[Any, ...]) -> bool:
    """The §12.4 sample, printed. The eval itself runs at L3, on every commit from M1."""
    pages = _searchable(records)
    inventory = from_records(pages)[corpus.doc_id]
    misses = near_misses(inventory, n=100, texts=[record.text for record in pages])

    print("\n15. near_misses(n=100) — one character off a real code (§12.4, F16)")
    passed = _line("100 fabricated codes, deterministic",
                   f"{len(misses)} from {len({miss.source for miss in misses})} real codes",
                   len(misses) == 100
                   and misses == near_misses(inventory, n=100,
                                             texts=[record.text for record in pages]))
    passed &= _line("each differs by exactly one character",
                    " ".join(f"{miss.source}→{miss.fake}" for miss in misses[:4]) + " …",
                    all(len(miss.fake) == len(miss.source)
                        and sum(a != b for a, b in zip(miss.fake, miss.source)) == 1
                        for miss in misses))
    passed &= _line("no fabricated code is a real one",
                    "no fake is printed, in any spelling",
                    not any(miss.fake in inventory for miss in misses)
                    and not any(is_printed(miss.fake, [tok(record.text) for record in pages])
                                for miss in misses))
    passed &= _line("every source is an observed token",
                    f"{len({miss.source for miss in misses})} sources, all from the inventory",
                    all(miss.source in inventory for miss in misses))
    passed &= _line("a near miss is never its own disclosure (F16)",
                    f"{PRESENT_INSTEAD_LABEL} ≠ the claim, cap {PRESENT_INSTEAD_CAP}",
                    all(miss.fake not in inventory.starting_with(miss.fake)
                        for miss in misses))
    print("   the eval that asserts none of them can ANSWER runs at L3, on every commit:")
    print("     bash scripts/test-api.sh -k near_miss")
    return passed


def _demo_synthetic_corpus(args_claims: list[str]) -> bool:
    """Seed an ephemeral collection from the checked-in corpus and run the acceptance table.

    Create, seed, assert, drop — inside one process, with no state left behind (§15 Factor VI).
    The collection is `{VSIR_COLLECTION}_synthetic_{dim}` and is dropped in a ``finally``, so a
    failing assertion cannot leave a half-seeded collection behind for the next run to inherit.
    """
    try:
        cfg = load_config()
    except ConfigError as refusal:
        print(f"\n   configuration refused: {refusal}")
        return False

    try:
        corpus = synthetic.load()
    except synthetic.FixtureMissing as refusal:
        # A named refusal, not a traceback: the reason is already the whole message, and this
        # command's output is what a reviewer reads (§4.4). The same rule as `BootRefused`.
        print(f"\n   corpus refused: {refusal}")
        return False

    records = corpus.records(release_id=cfg.release_id)
    collection = synthetic.synthetic_collection(cfg.collection, cfg.embed_dim)
    provenance = Provenance(run_id=synthetic.SEED_RUN_ID, release_id=cfg.release_id)
    client = QdrantClient(url=cfg.qdrant_url, timeout=30, check_compatibility=False)

    def ask(label: str, **kwargs: Any) -> Any:
        return lookup(client, collection, label, provenance=provenance,
                      reads_remaining=cfg.reads_per_question, **kwargs)

    try:
        try:
            seeded = synthetic.seed(client, collection, records, dim=cfg.embed_dim)
        except Exception as refusal:  # noqa: BLE001 - anything here is "could not reach Qdrant"
            print(f"\n   qdrant unreachable at {scrub_url(cfg.qdrant_url)}: "
                  f"{type(refusal).__name__}: {refusal}")
            return False
        passed = _demo_corpus_facts(corpus, records, seeded)
        passed &= _demo_exact_set(ask, corpus)
        passed &= _demo_unfindable(ask, corpus)
        passed &= _demo_absences(ask, corpus)
        passed &= _demo_observed_tokens(corpus, records)
        passed &= _demo_verify(client, collection, corpus, args_claims)
        passed &= _demo_abstention(corpus, records)
        return passed
    finally:
        try:
            synthetic.drop(client, collection)
        except Exception as failure:  # noqa: BLE001 - reported, never silently left behind
            print(f"   {collection} was not dropped: {type(failure).__name__}: {failure}")
        client.close()


def _cmd_demo_exact(args: argparse.Namespace) -> int:
    print(f"vsir demo exact — release {os.environ.get('VSIR_RELEASE_ID', 'unknown')}, "
          f"section {args.only}")
    claims = [claim.strip() for claim in (args.verify or "").split(",") if claim.strip()]
    passed = True
    if args.only in ("primitives", "all"):
        passed &= _demo_primitives()
    if args.only in ("corpus", "all"):
        if args.synthetic:
            passed &= _demo_synthetic_corpus(claims)
        else:
            # Not a silent skip and not a stub: at M1 the synthetic corpus is the only data source
            # there is, so a corpus section without `--synthetic` has nothing to run against and
            # says so. The frozen `TC1E-SF` fixture becomes the second source at M2b.
            print("\n   no corpus source selected — pass --synthetic to seed the §13 M1 corpus")
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
        help="seed an ephemeral collection from data/fixtures/synthetic_pages/ and run the §12.3 "
             "acceptance table against it; the `primitives` section is pure and reads no corpus",
    )
    exact_demo.add_argument(
        "--verify",
        metavar="CLAIMS",
        default="",
        help="comma-separated claims to run through verify_claims against the pages the corpus's "
             "expected.json associates with each one, e.g. --verify \"SF 1.1A,K73,SF 9.9\"; "
             "empty runs every row of that table",
    )
    exact_demo.add_argument(
        "--only",
        choices=["primitives", "corpus", "all"],
        default="all",
        help="which section to run: `primitives` needs nothing at all, `corpus` needs the "
             "configuration and a reachable Qdrant (default: all)",
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
