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
import json
import os
import signal
from pathlib import Path
from types import FrameType
from typing import Any

from qdrant_client import QdrantClient

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import DPI_ANSWER, VLM_BACKENDS, ConfigError, load_config, scrub_url
from vsir.core import ids
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
from vsir.ingest import extract as extract_module
from vsir.ingest import manifest, probe, render
from vsir.ingest import window as window_module
from vsir.ingest.extract import S2_SCHEMA_HASH
from vsir.serve.caps import (
    ToolError,
    as_tool_error,
    validate_budget,
    validate_cap,
    validate_dpi,
    validate_fetch_megapixels,
    validate_fetch_pages,
    validate_read_pages,
    validate_region,
    validate_scope,
)
from vsir.serve.envelope import Provenance, ToolEnvelope, VerifyResult
from vsir.vlm import VlmError, backend as vlm_backend
from vsir.vlm import cache as vlm_cache
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
    ("fetch, 12.5 MP", lambda: validate_fetch_megapixels(12.5), "fetch_budget_exceeded"),
    ("dpi=100", lambda: validate_dpi(100), "dpi_not_allowed"),
    ("dpi=300, no region", lambda: validate_dpi(300, None), "dpi_requires_region"),
    ("region=[0, 0, 2, 2]", lambda: validate_region([0, 0, 2, 2]), "region_invalid"),
    ("cap=0", lambda: validate_cap(0), "cap_out_of_range"),
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
    print("   every bound §7.3 tabulates, plus the two parameters it leaves implicit:")
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
        # The gate is `core/`'s, which knows nothing about HTTP, and the translation is `serve/`'s.
        # One check, one translation — and `lookup` raises the typed 400, not the domain error.
        typed = as_tool_error(refusal)
        correct = typed.code == "filter_unknown_key" and typed.http_status == 400
        passed &= correct
        print(f"   as_tool_error(...) -> {typed.http_status} {typed.code} {typed.details}"
              f"  {_verdict(correct)}")
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


# ── `vsir ingest` — steps 01-05 of §6.1 (M2a; the rest of the ladder lands with U008-U011) ───────

#: The steps `--until` can stop at, in pipeline order. Later units extend the list rather than
#: adding a second command: §6.1 is one pipeline and `vsir ingest` is its one operational surface.
INGEST_STEPS = ("manifest", "probe", "render", "facts", "window", "extract")

_RULE_WIDTH = 78


def _step(number: str, title: str) -> None:
    print(f"\n{number} {title} " + "─" * max(0, _RULE_WIDTH - len(number) - len(title) - 2))


def _check(description: str, observed: str, ok: bool) -> bool:
    """One assertion over two lines: the claim, then what was actually observed.

    `_line`'s single fixed-width row is right for `demo exact`, where every observation is a status
    and a page list. These observations are sentences, and truncating the evidence to fit a column
    is how a reviewer stops reading it.
    """
    print(f"   {_verdict(ok):<5} {description}")
    print(f"         {observed}")
    return ok


def _short(digest: str, keep: int = 16) -> str:
    return f"{digest[:keep]}…" if len(digest) > keep else digest


def _declared(flag: bool) -> str:
    return "declared" if flag else "undeclared — the default, and recorded as such (register A4)"


class IngestRefused(Exception):
    """A named, non-zero refusal from the ingest CLI. Never a warning followed by a partial run."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _backend(cfg: Any) -> Any:
    """The VLM backend `VSIR_VLM` names — one configuration lookup, no branch (§15 Factor X).

    The refusal is re-raised as an :class:`IngestRefused` so the command's exit path is the same
    for a missing fixture directory as for a missing credential: a named code and a non-zero exit,
    never a partial run (§4.3).
    """
    try:
        return vlm_backend(cfg)
    except VlmError as refusal:
        raise IngestRefused(refusal.code, str(refusal), **refusal.details) from refusal


def _ingest(args: argparse.Namespace, cfg: Any) -> bool:
    """Run steps 01-06 and print what each one decided. Returns whether the assertions passed.

    The run id is not a parameter: it is bound into the correlation context by the caller, so every
    event any of these steps logs carries it without a step having to remember to pass it on
    (§11.4). Nothing here holds it, and nothing here holds state between calls.
    """
    source = Path(args.pdf)
    until = args.until

    # ── 01 manifest ──────────────────────────────────────────────────────────────────────────
    _step("01", "manifest — identity, from the filename, the metadata and the uploader")
    doc = manifest.build(
        source,
        doc_id=args.doc_id, revision=args.revision, doc_type=args.doc_type,
        subjects=[s.strip() for s in (args.subjects or "").split(",") if s.strip()],
        tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        uploader=args.uploader,
    )
    _log.info("ingest_step", step="manifest", doc_id=doc.doc_id, revision=doc.revision,
              doc_type=doc.doc_type, subjects=list(doc.subjects), tags=list(doc.tags))
    print(f"   doc_id       {doc.doc_id}")
    print(f"   revision     {doc.revision}   ({_declared(doc.revision_declared)})")
    print(f"   doc_type     {doc.doc_type}   ({_declared(doc.doc_type_declared)})")
    print(f"   subjects     {', '.join(doc.subjects) or '—'}")
    print(f"   tags         {', '.join(doc.tags) or '—'}")
    print(f"   source       {source}  ·  {doc.size_bytes:,} bytes")
    print("   no content sniffing: §6.1 step 01 takes facets from the filename, the file's own")
    print("   metadata and the uploader, and this module contains no grammar of any kind")
    if until == "manifest":
        return True

    # ── 02 probe ─────────────────────────────────────────────────────────────────────────────
    _step("02", "probe — the text layer, and the only writer of `text` (I2)")
    probed = probe.run(source)
    _log.info("ingest_step", step="probe", page_count=probed.page_count,
              pages_with_text=probed.pages_with_text, content_hash=probed.content_hash,
              probe_version=probed.probe_version)
    print(f"   page_count {probed.page_count} · {probed.probe_version} · "
          f"content_hash {_short(probed.content_hash)}")
    print(f"   pages with text {probed.pages_with_text}/{probed.page_count} "
          f"(searchable_ratio {probed.searchable_ratio:.2f}) · "
          f"s2_input_mode {probed.s2_input_mode}")
    print(f"   front sample ({probe.PROBE_SAMPLE_PAGES} pages) {probed.sample_chars_per_page} "
          f"chars/page vs a {probe.BORN_DIGITAL_MIN_CHARS} threshold — extraction happened anyway,")
    print("   which is register A1: one `else` there throws away a mixed document's whole text")
    if until == "probe":
        _print_pages(probed, rasters=None)
        return True

    # ── 03 render ────────────────────────────────────────────────────────────────────────────
    _step("03", f"render — page rasters at dpi {DPI_ANSWER}, in memory, never written down")
    rasters = render.render_pages(source, range(1, probed.page_count + 1), dpi=DPI_ANSWER,
                                  content_hash=probed.content_hash)
    cache = render.cache_info()
    _log.info("ingest_step", step="render", dpi=DPI_ANSWER, rasters=len(rasters),
              cache_hits=cache["hits"], cache_misses=cache["misses"], persisted=0)
    print(f"   {len(rasters)} rasters at dpi {DPI_ANSWER}, "
          f"{rasters[0].width}x{rasters[0].height} px, "
          f"{sum(len(r.png) for r in rasters) / 1_048_576:.1f} MB held in memory")
    print(f"   raster cache: {cache['misses']} rendered, {cache['hits']} served from the LRU "
          f"(max {cache['maxsize']}) — a cache, never a source of truth (§4.2, register E3)")
    print("   0 bytes written to the filesystem")
    _print_pages(probed, rasters=rasters)
    if until == "render":
        return True

    # ── 04 S1 document facts ─────────────────────────────────────────────────────────────────
    _step("04", "S1 document facts — cached per document, because the ladder rides on them")
    backend = _backend(cfg)
    key = vlm_cache.facts_key(probed.content_hash, vlm_model=cfg.vlm_model,
                              prompt_version=cfg.prompt_version)
    print(f"   backend      {backend.name}  "
          f"(VSIR_VLM={cfg.vlm}, chosen by configuration — never by a code branch)")
    print(f"   facts_key    {_short(key)}  "
          f"(content hash ‖ {cfg.vlm_model} ‖ {cfg.prompt_version})")
    try:
        facts, facts_entry = extract_module.document_facts(
            backend, source=source, probed=probed, vlm_model=cfg.vlm_model,
            prompt_version=cfg.prompt_version, dpi=DPI_ANSWER)
    except VlmError as refusal:
        raise IngestRefused(refusal.code, str(refusal), **refusal.details) from refusal
    _log.info("ingest_step", step="facts", facts_key=key, origin=facts_entry.origin,
              toc_entries=len(facts.toc))
    print(f"   {facts_entry.origin:<12} {facts_entry.path or backend.name}  "
          f"({len(facts_entry.body):,} bytes, verbatim)")
    print(f"   title \"{facts.title}\" · lang {', '.join(facts.lang) or '—'} · "
          f"effectivity \"{facts.effectivity_basis}\"")
    usable = window_module.chapter_ranges(facts.toc, probed.page_count)
    print(f"   toc          {len(facts.toc)} entries, "
          f"{len(usable)} usable chapter range(s) — this is what picks the ladder")
    for entry in facts.toc:
        print(f"                p{entry.page_no:<4} {entry.title}")
    mismatch = doc.disagreement(facts)
    print(f"   the model disagrees with a DECLARED facet: {mismatch or 'nothing'} "
          f"(the operator's inventory wins; the reading is kept as a cross-check)")
    if until == "facts":
        return True

    # ── 05 window + extract_key ──────────────────────────────────────────────────────────────
    _step("05", "window — the ladder, and the receipt that stops the pipeline paying twice")
    plan = window_module.plan(probed.page_count, toc=facts.toc, size_bytes=probed.size_bytes,
                              document=doc.doc_id)
    keys = _window_keys(source, plan, probed, cfg)
    _log.info("ingest_step", step="window", level=plan.level, windows=len(plan.windows),
              parallel=plan.parallel,
              ranges=[[w.start, w.end] for w in plan.windows], extract_keys=list(keys))
    print(f"   level {plan.level} · {'chapter-aligned' if plan.level else 'whole document'} · "
          f"parallel={plan.parallel}")
    print(f"   v1 climbs to level {window_module.MAX_LADDER_LEVEL} and refuses the blind cut by "
          f"name (§6.2, §2.5 B); bisection re-bills, it never pads")
    print(f"   {'#':<3} {'pages':<9} {'n':>3}  extract_key")
    for number, (win, key) in enumerate(zip(plan.windows, keys), start=1):
        print(f"   {number:<3} {f'{win.start}-{win.end}':<9} {win.pages:>3}  {_short(key, 24)}")
    print(f"   coverage: pages 1-{probed.page_count}, each exactly once — "
          f"{plan.covers(probed.page_count)}")
    print(f"   distinct keys: {len(set(keys))}/{len(keys)}")
    warm = render.cache_info()
    print(f"   keying the windows re-read every page from the raster cache: "
          f"{warm['hits']} hits, {warm['misses']} renders in this process")
    if until == "window":
        return _assertions(args, source, doc, probed, plan, keys, extraction=None)

    # ── 06 S2 extraction ─────────────────────────────────────────────────────────────────────
    _step("06", "S2 extraction — the call that spends the money, and the receipt that avoids it")
    try:
        extraction = extract_module.extract(
            backend, source=source, plan=plan, probed=probed, vlm_model=cfg.vlm_model,
            prompt_version=cfg.prompt_version, dpi=DPI_ANSWER)
    except VlmError as refusal:
        raise IngestRefused(refusal.code, str(refusal), **refusal.details) from refusal
    _log.info("ingest_step", step="extract", windows=len(extraction.windows),
              page_forms=extraction.page_forms, bisections=list(extraction.bisections),
              origins=sorted({w.origin for w in extraction.windows}))
    print(f"   schema       WindowOut · hash {_short(S2_SCHEMA_HASH, 24)} — computed from the "
          f"schema, never a hand-bumped integer")
    print(f"   {'#':<3} {'pages':<9} {'origin':<8} {'forms':>5} {'sect':>5} {'codes':>6}  "
          f"{'bytes':>7}  extract_key")
    for number, window in enumerate(extraction.windows, start=1):
        print(f"   {number:<3} {f'{window.window.start}-{window.window.end}':<9} "
              f"{window.origin:<8} {window.page_forms:>5} {window.sightings:>5} "
              f"{window.codes:>6}  {len(window.entry.body):>7,}  {_short(window.key, 24)}")
    print(f"   {extraction.page_forms} page forms over {len(extraction.windows)} window(s); "
          f"bisections this run: {list(extraction.bisections) or 'none'}")
    print(f"   the model returned 0 characters of page text: `text` has exactly one writer, "
          f"ingest/probe.py (I2)")
    _print_window_out(extraction, raw=args.raw)

    return _assertions(args, source, doc, probed, plan, keys, extraction=extraction)


def _print_window_out(extraction: Any, *, raw: bool) -> None:
    """The verbatim response — which is the only thing step 06 actually produces (§6.3).

    One page form per window by default, because that is the unit a reviewer reads: it is where
    ``page_index`` being window-local is visible, and where "presence, never extent" is visible as
    the *absence* of any span field. ``--raw`` prints every window's body in full, unmodified: it
    is a receipt, and a receipt that has been reformatted for display is somebody's summary of one.
    """
    for number, window in enumerate(extraction.windows, start=1):
        first = window.window.start
        print(f"\n   window {number} ({first}-{window.window.end}) — the verbatim response"
              + ("" if raw else f", page_index 1 of {window.page_forms}"))
        body = (window.entry.body if raw
                else json.dumps(window.out.pages[0].model_dump(), indent=2, sort_keys=True))
        for line in body.splitlines():
            print(f"     {line}")
        if not raw:
            print(f"     … {window.page_forms - 1} more page form(s); --raw prints the "
                  f"whole body")
        print(f"     page_index 1 is PDF page {window.window.absolute(1)}: "
              f"abs = window.start + page_index - 1, computed in one place (§6.4)")


def _print_pages(probed: Any, rasters: Any) -> None:
    print()
    header = f"   {'page':>4}  {'label':<6} {'has_text':<9} {'text_trust':<11} {'chars':>6}"
    print(header + (f"  raster sha256 @{DPI_ANSWER}" if rasters else ""))
    for page in probed.pages:
        row = (f"   {page.page_no:>4}  {page.label or '—':<6} {str(page.has_text).lower():<9} "
               f"{page.text_trust:<11} {page.chars:>6}")
        if rasters:
            row += f"  {_short(rasters[page.page_no - 1].sha256, 24)}"
        print(row)


def _window_keys(source: Path, plan: Any, probed: Any, cfg: Any) -> tuple[str, ...]:
    """One `extract_key` per window, over the ordered page image hashes S2 will see (§6.3)."""
    return tuple(
        vlm_cache.extract_key(
            render.page_hashes(source, win.page_numbers, dpi=DPI_ANSWER,
                               content_hash=probed.content_hash),
            vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version,
            dpi=DPI_ANSWER, schema_hash=S2_SCHEMA_HASH,
        )
        for win in plan.windows
    )


def _assertions(args: argparse.Namespace, source: Path, doc: Any, probed: Any,
                plan: Any, keys: tuple[str, ...], *, extraction: Any) -> bool:
    """Check the run against the numbers checked in beside the corpus, never against itself."""
    expected_path = Path(args.fixture or "") / "expected.json"
    if not expected_path.is_file():
        print(f"\n   no acceptance table at {expected_path} — nothing to check this run against")
        return True

    table = json.loads(expected_path.read_text())
    print(f"\nassertions — {expected_path}")
    passed = True

    passed &= _check(f"{table['page_count']} pages, as the fixture declares",
                    f"probe found {probed.page_count}",
                    probed.page_count == table["page_count"])
    ranges = [[w.start, w.end] for w in plan.windows]
    passed &= _check(f"{len(table['windows'])} windows at level {table['ladder_level']}",
                    " · ".join(f"{a}-{b}" for a, b in ranges),
                    ranges == table["windows"] and plan.level == table["ladder_level"])
    passed &= _check("each window's extract_key is distinct",
                    f"{len(set(keys))} distinct of {len(keys)}",
                    len(set(keys)) == len(keys))
    passed &= _check("coverage is the whole document, once",
                    f"pages 1-{probed.page_count}", plan.covers(probed.page_count))

    without = [p.page_no for p in probed.pages if not p.has_text]
    passed &= _check("has_text == false implies text_trust == no_text (§5.7)",
                    f"pages {without} have no text layer",
                    without == table["pages_without_text"]
                    and all(probed.page(n).text_trust == "no_text" for n in without))
    sample = probed.sample_chars_per_page
    passed &= _check("the mixed-document trap is armed (register A1)",
                    f"the front sample averages {sample} chars/page, under "
                    f"{table['mixed_document']['born_digital_min_chars']} — and all "
                    f"{probed.pages_with_text} text pages were still extracted",
                    sample < table["mixed_document"]["born_digital_min_chars"]
                    and probed.pages_with_text == probed.page_count - len(without))

    labels = {str(page.page_no): page.label for page in probed.pages}
    passed &= _check("the printed labels are the fixture's, offset and all (I4, F7)",
                    f"PDF page {table['first_labelled_page']} prints "
                    f"\"{table['printed_labels'][str(table['first_labelled_page'])]}\" — "
                    f"label = index {table['label_offset']:+d}",
                    labels == table["printed_labels"])

    trap = table["crop_trap"]
    cropped = render.render_page(source, trap["page"], dpi=DPI_ANSWER, region=trap["region"],
                                 content_hash=probed.content_hash)
    full = render.render_page(source, trap["page"], dpi=DPI_ANSWER,
                              content_hash=probed.content_hash)
    text = probed.page(trap["page"]).text
    passed &= _check("the crop trap: text comes from the FULL page, never a crop (F15)",
                    f"page {trap['page']}'s raster region {trap['region']} keeps "
                    f"{cropped.height}/{full.height} px of the sheet and cuts off at "
                    f"{trap['region'][3]:.2f}; \"{trap['label']}\" sits at "
                    f"{trap['bbox_top_fraction']:.3f} — outside it, and in the extracted text",
                    trap["label"] in text
                    and trap["bbox_top_fraction"] > trap["region"][3]
                    and cropped.height < full.height)

    hashes = [render.render_page(source, n, dpi=DPI_ANSWER,
                                 content_hash=probed.content_hash).sha256
              for n in range(1, probed.page_count + 1)]
    passed &= _check(f"the dpi {DPI_ANSWER} rasters are byte-identical to the fixture's",
                    f"{sum(a == b for a, b in zip(hashes, table['render']['page_sha256']))}"
                    f"/{probed.page_count} page hashes match",
                    hashes == table["render"]["page_sha256"])
    if extraction is not None:
        passed &= _extraction_assertions(table["extraction"], probed, extraction)
    return passed


def _extraction_assertions(table: dict, probed: Any, extraction: Any) -> bool:
    """Step 06's own rows: the offset, the schema, and the two traps the fixture wires in."""
    passed = _check(f"{table['page_forms']} page forms over {table['windows']} window(s)",
                    f"{extraction.page_forms} forms, "
                    f"{len(extraction.windows)} window(s), "
                    f"origins {sorted({w.origin for w in extraction.windows})}",
                    extraction.page_forms == table["page_forms"]
                    and len(extraction.windows) == table["windows"])

    # §6.4 check (1), the structural half: every window's indices are exactly 1..N, so the
    # absolute page of every form resolves and none of them lands twice.
    resolved = {}
    for window in extraction.windows:
        for form in window.out.pages:
            resolved[window.window.absolute(form.page_index)] = form
    second = extraction.windows[1].window if len(extraction.windows) > 1 else None
    passed &= _check("page_index is window-local, and the offset resolves each form once (§6.4)",
                    (f"window 2 starts at PDF page {second.start} and its page_index 1 is PDF "
                     f"page {second.absolute(1)}; " if second else "")
                    + f"{len(resolved)} distinct absolute pages of {probed.page_count}",
                    sorted(resolved) == list(range(1, probed.page_count + 1)))

    kinds = {str(page_no): form.kind for page_no, form in sorted(resolved.items())}
    passed &= _check("every page_kind is one of §5.2's eight, and matches the fixture",
                    f"{sorted(set(kinds.values()))}",
                    kinds == table["page_kinds"]
                    and set(kinds.values()) <= set(extract_module.PAGE_KINDS))

    missing = {page_no: form.missing_summary_langs()
               for page_no, form in resolved.items() if form.missing_summary_langs()}
    passed &= _check("one summary per language on every page, never a blended one (D5)",
                    f"{len(resolved)} pages, {sum(len(f.summaries) for f in resolved.values())} "
                    f"summaries, {len(missing)} page(s) missing one",
                    not missing)

    # F6: reported on one page, printed on its neighbour, and both inside the same window.
    trap = table["reattribution"]
    here, there = resolved[trap["page"]], trap["from_page"]
    window_of = next(w.window for w in extraction.windows
                    if w.window.start <= trap["page"] <= w.window.end)
    passed &= _check("the reattribution trap: a code reported on the page beside the one that "
                    "prints it (F6)",
                    f"page {trap['page']} reports {trap['code']}, which is absent from its own "
                    f"text and present in page {there}'s; both are inside window "
                    f"{window_of.start}-{window_of.end}",
                    trap["code"] in here.codes
                    and trap["code"] not in probed.page(trap["page"]).text
                    and trap["code"] in probed.page(there).text
                    and window_of.start <= there <= window_of.end)

    # I2/F14: reported by the model, printed nowhere. It must never reach the exact surface.
    loose = table["ungrounded"]
    passed &= _check("the ungrounded code: reported by the model, printed on no page (I2, F14)",
                    f"page {loose['page']} reports {loose['code']}; it appears in "
                    f"{sum(1 for p in probed.pages if loose['code'] in p.text)} page texts",
                    loose["code"] in resolved[loose["page"]].codes
                    and not any(loose["code"] in page.text for page in probed.pages))

    # The structural guarantee of §5.2: extent is not a field the model could fill in even if it
    # wanted to, which is what lets a section straddle a fold and survive it (F8).
    section_fields = set(extract_module.SectionRef.model_fields)
    passed &= _check("no field in which the model could claim how far a section reaches (§5.2)",
                    f"SectionRef carries {sorted(section_fields)}",
                    not section_fields & {"span", "pages", "page_range", "page_count", "extent"})
    return passed


def _cmd_ingest(args: argparse.Namespace) -> int:
    if args.vlm:
        os.environ["VSIR_VLM"] = args.vlm
    if args.fixture:
        os.environ["VSIR_FIXTURE"] = args.fixture
    try:
        cfg = load_config()
    except ConfigError as refusal:
        _log.error("ingest_refused", reason="configuration", detail=str(refusal))
        print(f"   configuration refused: {refusal}")
        return EXIT_REFUSED
    args.fixture = args.fixture or cfg.fixture_dir

    identifier = ids.run_id()
    with vsir_logging.correlate(run_id=identifier):
        print(f"vsir ingest — release {cfg.release_id} · run {identifier} · until {args.until}")
        _log.info("ingest_started", pdf=str(args.pdf), until=args.until, vlm=cfg.vlm,
                  vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version, dpi=DPI_ANSWER)
        try:
            passed = _ingest(args, cfg)
        except (IngestRefused, window_module.WindowError, render.RenderError) as refusal:
            _log.error("ingest_refused", reason=refusal.code, detail=str(refusal),
                       **getattr(refusal, "details", {}))
            print(f"\n   REFUSED  {refusal.code}: {refusal}")
            return EXIT_REFUSED
        except FileNotFoundError as refusal:
            _log.error("ingest_refused", reason="source_missing", detail=str(refusal))
            print(f"\n   REFUSED  source_missing: {refusal}")
            return EXIT_REFUSED
        _log.info("ingest_complete", until=args.until, passed=passed)
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

    ingest_parser = commands.add_parser(
        "ingest",
        help="run the ingestion pipeline of §6.1 over one PDF; steps 01-05 at M2a",
    )
    ingest_parser.add_argument("pdf", help="the source PDF")
    ingest_parser.add_argument(
        "--until", choices=list(INGEST_STEPS), default=INGEST_STEPS[-1],
        help=f"stop after this step (default: {INGEST_STEPS[-1]}, the last one built)",
    )
    ingest_parser.add_argument(
        "--vlm", choices=list(VLM_BACKENDS), default=None,
        help="override VSIR_VLM for this process — the backend is chosen by configuration, "
             "never by a code branch (§15 Factor X)",
    )
    ingest_parser.add_argument(
        "--fixture", default=None,
        help="override VSIR_FIXTURE: the replay directory frozen S1/S2 responses are keyed into, "
             "and where the acceptance table beside the corpus is read from (D10)",
    )
    ingest_parser.add_argument(
        "--raw", action="store_true",
        help="print every window's VERBATIM response body in full rather than its first page "
             "form: it is the receipt (§6.3), and a receipt reformatted for display is a summary",
    )
    ingest_parser.add_argument("--doc-id", default=None,
                               help="declare the revision-stable document id (§5.1)")
    ingest_parser.add_argument("--revision", default=None,
                               help="declare the revision; the operator's value is authoritative")
    ingest_parser.add_argument("--doc-type", default=None, help="declare the document type")
    ingest_parser.add_argument("--subjects", default="",
                               help="comma-separated machine/model subjects (§5.3)")
    ingest_parser.add_argument("--tags", default="", help="comma-separated uploader tags (§5.3)")
    ingest_parser.add_argument("--uploader", default="", help="who supplied the document")
    ingest_parser.set_defaults(handler=_cmd_ingest)

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
