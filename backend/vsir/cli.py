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
import dataclasses
import json
import math
import os
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import Any, Mapping, Sequence

from qdrant_client import QdrantClient

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import (
    COMPOSITION_VERSION,
    DPI_ANSWER,
    DPI_INDEX,
    LOOKUP_CAP,
    VLM_BACKENDS,
    ConfigError,
    load_config,
    scrub_url,
)
from vsir.core import ids
from vsir.core import observed_tokens as observed_tokens_module
from vsir.core.exact import UnknownScopeKey, exact_filter, phrases_of
from vsir.core.nearmiss import is_printed, near_misses
from vsir.core.observed_tokens import from_records, is_code_like, is_searchable
from vsir.core.present_instead import PRESENT_INSTEAD_CAP, PRESENT_INSTEAD_LABEL
from vsir.core.verify import page_checks, verify_claims
from vsir.core.tok import tok, token_set
from vsir.core.variants import preserves_characters, variants
from vsir.doctor import BootRefused, doctor
from vsir.eval import abstention, acceptance, synthetic
from vsir.ingest import derive as derive_module
from vsir.ingest import embed as embed_module
from vsir.ingest import export as export_module
from vsir.ingest import extract as extract_module
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest import gates as gates_module
from vsir.ingest import index as index_module
from vsir.ingest import run as run_module
from vsir.ingest import manifest, probe, render
from vsir.ingest import stitch as stitch_module
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
from vsir.mcp import server as mcp_server
from vsir.serve import app as app_module
from vsir.serve import auth as auth_module
from vsir.serve.app import config_of, create_app
from vsir.serve.envelope import Provenance, ToolEnvelope, VerifyResult
from vsir.vlm import VlmError, backend as vlm_backend
from vsir.vlm import cache as vlm_cache
from vsir.vlm import record as vlm_record
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
INGEST_STEPS = ("manifest", "probe", "render", "facts", "window", "extract", "derive", "stitch",
                "embed", "index", "publish")

#: The steps that need a reachable Qdrant. Steps 01-08 are pure functions of the PDF and the
#: fixture, which is what lets the whole of derivation and stitching be asserted at L0/L1; step 09
#: reads the embedding cache off the index and step 10 writes to it, so both refuse
#: `qdrant_unavailable` with no store rather than running without one (§11.3). Step 11 is the
#: control plane and the publish flip, which are Qdrant by definition (D9, §6.7).
STORE_BACKED_STEPS: tuple[str, ...] = ("embed", "index", "publish")

_RULE_WIDTH = 78

#: What a §6.4 refusal that names no check is reported as. It cannot happen through
#: `derive.check_offset`, which always names one; printing an empty string would be worse.
OFFSET_CHECK_UNKNOWN = "offset"

#: How far a vector read back out of Qdrant may differ from the one that was written. Qdrant keeps
#: a cosine vector as float32 and normalises it on the way in, so the round trip is lossy by about
#: 1e-9 per component. Anything beyond this is a *different vector*, not a storage artefact.
VECTOR_STORAGE_TOLERANCE = 1e-6


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


@dataclasses.dataclass
class _RunHandle:
    """A handle on the in-flight run, so ``SIGTERM`` can checkpoint it (§15 Factor IX, F17).

    Deliberately **not** state. The run's truth is its point in `vsir_runs` (D9) and every step
    writes there as it finishes; this holds the client and the last record written so the signal
    handler can mark the run ``stopped`` without having to find it again. Nothing reads it to make
    a decision, and a process that dies without unwinding leaves a run whose lease simply expires.
    """

    client: Any = None
    runs_collection: str = ""
    record: Any = None

    def stopped(self, reason: str = "sigterm") -> None:
        """What the signal handler calls: checkpoint the run, publish nothing (I7)."""
        if self.client is None or self.record is None:
            return
        run_module.stop(self.client, self.runs_collection, self.record, reason=reason,
                        step=self.record.step)


def _owner() -> str:
    """Who this worker is, for the advisory lease: host and pid, which is enough to find it.

    Not a configured identity. The lease's job is to stop a *second* worker starting by accident
    and to tell an operator which process to look at; a name an operator has to set would be one
    more thing to get wrong, and the lease is advisory either way (D9).
    """
    return f"{os.uname().nodename}:{os.getpid()}"


def _progress(handle: _RunHandle, cfg: Any, **fields: Any) -> Any:
    """Renew the lease and record progress, or do nothing when the run is store-free.

    Returns the record so the caller can keep the handle current: a step that finished and did not
    renew is a step whose lease can expire under it, and an expired lease is what `--steal` is for.
    """
    if handle.client is None or handle.record is None:
        return handle.record
    return run_module.renew(handle.client, cfg.runs_collection, handle.record, **fields)


def _note_windows(handle: _RunHandle, cfg: Any, *, doc: Any, plan: Any, keys: Sequence[str],
                  checkpoint: str, state: str, extraction: Any = None,
                  derivation: Any = None) -> None:
    """Write one window point per window of the plan (§6.7, D9).

    The window points are what `offset_check` reads at step 11 and what `--resume` reads at U025,
    and they are written as each step finishes rather than at the end — a run killed at window 2
    of 3 leaves two windows recorded, which is the difference between resumable and re-billable.
    """
    if handle.client is None or handle.record is None:
        return
    returned = {}
    bisected: set[tuple[int, int]] = set()
    if extraction is not None:
        returned = {(w.window.start, w.window.end): w for w in extraction.windows}
    if derivation is not None:
        bisected = set(derivation.bisected)
    for window, key in zip(plan.windows, keys):
        span = (window.start, window.end)
        found = returned.get(span)
        run_module.note_window(handle.client, cfg.runs_collection, run_module.WindowState(
            run_id=handle.record.run_id, doc_id=doc.doc_id, start=window.start, end=window.end,
            state=state, attempts=1 if found is not None else 0, checkpoint=checkpoint,
            extract_key=key, pages_returned=getattr(found, "page_forms", 0) if found else 0,
            # Reaching this point at all means §6.4's checks passed for this window: `derive`
            # raises rather than emitting records for a window it cannot place, and a bisected
            # window is a **pass** whose repair is recorded — F13's ladder is not a defect.
            offset_ok=True, bisected=span in bisected))


def _open_store(cfg: Any) -> Any:
    """The one Qdrant connection a store-backed run uses, or a typed `qdrant_unavailable`."""
    try:
        return QdrantClient(url=cfg.qdrant_url, timeout=60, check_compatibility=False)
    except Exception as failure:  # noqa: BLE001 - anything here is "could not reach Qdrant"
        raise IngestRefused("qdrant_unavailable",
                            f"{scrub_url(cfg.qdrant_url)}: {type(failure).__name__}: {failure}",
                            qdrant_url=scrub_url(cfg.qdrant_url)) from failure


def _backend(cfg: Any, record: str = "") -> Any:
    """The VLM backend `VSIR_VLM` names — one configuration lookup, no branch (§15 Factor X).

    The refusal is re-raised as an :class:`IngestRefused` so the command's exit path is the same
    for a missing fixture directory as for a missing credential: a named code and a non-zero exit,
    never a partial run (§4.3).

    ``record`` wraps it in the §12.1 recorder, which is what makes the M2b re-bill buy a permanent
    fixture instead of a one-off answer (`vlm/record.py`). Recording is a **flag on one run**, not
    configuration: an ambient record mode would let a fixture accumulate responses from runs
    nobody meant to freeze, and nothing about which responses are in a fixture may be accidental.
    """
    try:
        chosen = vlm_backend(cfg)
    except VlmError as refusal:
        raise IngestRefused(refusal.code, str(refusal), **refusal.details) from refusal
    return vlm_record.recording(chosen, record) if record else chosen


def _ingest(args: argparse.Namespace, cfg: Any, handle: _RunHandle) -> bool:
    """Run steps 01-11 and print what each one decided. Returns whether the assertions passed.

    The run id is not a parameter: it is bound into the correlation context by the caller, so every
    event any of these steps logs carries it without a step having to remember to pass it on
    (§11.4). Nothing here holds it, and nothing here holds state between calls — the run's own
    state lives in `vsir_runs` and is written as each step finishes (D9).
    """
    source = Path(args.pdf)
    until = args.until
    run_id = vsir_logging.correlation().get("run_id", "")

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
    if handle.client is not None:
        # The run point is written **before** the first window, not after the last: a run that
        # dies mid-flight has to be a run that exists, in a state that says so, with a lease that
        # expires (register E2 — `impl` kept this in a dict on a daemon thread, so a restart
        # stranded a paid run with no report and nothing to resume).
        handle.record = (
            run_module.claim(handle.client, cfg.runs_collection, run_id, owner=_owner(),
                             steal=args.steal)
            if args.resume else
            run_module.start(handle.client, cfg.runs_collection, run_id=run_id, doc_id=doc.doc_id,
                             revision=doc.revision, release_id=cfg.release_id,
                             collection=cfg.pages_collection, owner=_owner()))
        if (handle.record.doc_id, handle.record.revision) != (doc.doc_id, doc.revision):
            raise IngestRefused(
                "run_document_mismatch",
                f"run {run_id} is {handle.record.doc_id}@{handle.record.revision} and this "
                f"invocation is {doc.doc_id}@{doc.revision}: resuming a run against a different "
                f"document would write this document's pages under that run's id, and publish "
                f"would then flip a set of points nobody meant (§6.7)",
                run_id=run_id, run_doc=f"{handle.record.doc_id}@{handle.record.revision}",
                invocation_doc=f"{doc.doc_id}@{doc.revision}")
        print(f"   run          {handle.record.run_id} · state {handle.record.state} · "
              f"lease {handle.record.lease.owner} until {handle.record.lease.expires_at}")
        print(f"   control      {cfg.runs_collection} (D9): one point per run, one per window, "
              f"and the observed-token inventory — never a dict on a daemon thread (register E2)")
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
    if args.record:
        # §12.1's `text.json`: the extractor's own output, frozen beside the receipts, so a level
        # that replays this fixture can rebuild every page record without the PDF — which is what
        # keeps `data/source/` gitignored and every downstream level free (OQ-1).
        written = vlm_record.freeze_text(args.record, probed)
        print(f"   recorded     {written}  ({probed.page_count} pages, {probed.probe_version})")
    handle.record = _progress(handle, cfg, step="probe", page_count=probed.page_count)
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
    backend = _backend(cfg, record=args.record)
    key = vlm_cache.facts_key(probed.content_hash, vlm_model=cfg.vlm_model,
                              prompt_version=cfg.prompt_version)
    print(f"   backend      {backend.name}  "
          f"(VSIR_VLM={cfg.vlm}, chosen by configuration — never by a code branch)")
    if args.record:
        print(f"   recording    {args.record}  "
              f"(every verbatim body frozen under its §6.3 key — §12.1)")
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
    handle.record = _progress(handle, cfg, step="window", windows_total=len(plan.windows))
    _note_windows(handle, cfg, doc=doc, plan=plan, keys=keys, checkpoint="window",
                  state=run_module.QUEUED)
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
    if args.record:
        # The tally, not a directory listing: a bisected window is two receipts, so "how many did
        # this run freeze" is a question only the recorder can answer (§6.2, §12.1).
        print(f"   recorded     {len(backend.recorded)} receipt(s) under {args.record} — "
              f"S1 and S2, each under the §6.3 key replay reads it back by")
        for path in backend.recorded:
            print(f"                {path}")
    _print_window_out(extraction, raw=args.raw)
    _note_windows(handle, cfg, doc=doc, plan=plan, keys=keys, checkpoint="extract",
                  state=run_module.RUNNING, extraction=extraction)
    handle.record = _progress(handle, cfg, step="extract")
    if until == "extract":
        return _assertions(args, source, doc, probed, plan, keys, extraction=extraction)

    # ── 07 derivation ────────────────────────────────────────────────────────────────────────
    _step("07", "derivation — the claim beside the evidence, and both checks of the offset proof")

    def reextract(half: Any) -> Any:
        """§6.4's *"bisect and re-bill"*, wired to the real step 06 (I4, F13).

        This argument is what makes the repair a **production** path rather than a capability.
        Without it `derive` re-raises, which is the honest answer for an inspection run with
        nothing to re-bill with — and would leave a document that could have been repaired
        failing instead. The halves are billed through the same `extract_window` the plan's own
        windows go through, so each gets its own `extract_key` over the pages it actually covers.
        """
        return extract_module.extract_window(
            backend, half, source=source, content_hash=probed.content_hash,
            page_count=probed.page_count, vlm_model=cfg.vlm_model,
            prompt_version=cfg.prompt_version, dpi=DPI_ANSWER)

    try:
        derivation = derive_module.derive(
            extraction, probed=probed, doc=doc, run_id=run_id,
            release_id=cfg.release_id, vlm_model=cfg.vlm_model,
            prompt_version=cfg.prompt_version, dpi=DPI_ANSWER, doc_lang=facts.lang,
            reextract=reextract)
    except derive_module.OffsetError as failure:
        # The repair was tried and could not finish — a half that fails the same way down to one
        # page, or a coverage hole. §11.1's `offset_check` is what judges that, so the run is
        # **gated** with the failing window named rather than dying with a traceback: I4 is proved
        # on every window or the document does not publish, and zero pages are queryable either
        # way (I7).
        return _offset_blocked(args, cfg, handle, doc=doc, probed=probed, plan=plan, keys=keys,
                               extraction=extraction, failure=failure)
    _log.info("ingest_step", step="derive", pages=len(derivation.pages),
              moves=len(derivation.moves),
              grounded_median=derivation.health.grounded_median,
              text_trust=derivation.health.text_trust,
              searchable_ratio=derivation.health.searchable_ratio)
    print(f"   §6.4 check (1) structural: every window returned page_index 1..N, so "
          f"abs = window.start + page_index - 1 resolves each form once")
    print(f"   §6.4 check (2) independent observation: {_observed(derivation)} model-read label(s) "
          f"phrase-match their OWN page's text; a match on a neighbour raises OffsetError")
    print(f"   grounded_rate median {derivation.health.grounded_median} over the "
          f"{derivation.health.pages_with_text} page(s) that have text — the "
          f"{derivation.health.page_count - derivation.health.pages_with_text} that do not rate "
          f"None and are ignored by the aggregate (§5.7)")
    print(f"   text_trust {derivation.health.text_trust} · searchable_ratio "
          f"{derivation.health.searchable_ratio:.2f} · no allowlist gate, no identifier grammar, "
          f"no keyword list (§2.4, §2.5 B)")
    for move in derivation.moves:
        print(f"   reattributed {move.code}: page {move.from_page_no} -> {move.to_page_no}, "
              f"inside window {move.window[0]}-{move.window[1]} (F6)")
    for page_no, code in derivation.ungrounded:
        print(f"   ungrounded {code} on page {page_no}: printed on no page, so it stays put, "
              f"counts against that page's grounded_rate and never enters `text` (I2)")
    _print_derived(derivation)
    _note_windows(handle, cfg, doc=doc, plan=plan, keys=keys, checkpoint="derive",
                  state=run_module.DONE, extraction=extraction, derivation=derivation)
    handle.record = _progress(handle, cfg, step="derive",
                              windows_done=len(getattr(extraction, "windows", ()) or ()))
    if until == "derive":
        return _assertions(args, source, doc, probed, plan, keys, extraction=extraction,
                           derivation=derivation, stitched=None)

    # ── 08 stitching ─────────────────────────────────────────────────────────────────────────
    _step("08", "stitching — the window folds deleted again, and section extent created once")
    stitched = stitch_module.stitch(derivation.pages, doc_id=doc.doc_id, revision=doc.revision)
    _log.info("ingest_step", step="stitch", pages=len(stitched.pages),
              sections=len(stitched.sections), straddling=len(stitched.straddling))
    print(f"   {len(stitched.sections)} section(s) from "
          f"{sum(len(p.sightings) for p in derivation.pages)} per-page sighting(s) — extent is "
          f"(min, max) over sightings and is created here, nowhere else (§5.2)")
    print(f"   section_id and series_id are keyword ARRAYS: a straddling page carries both, and a "
          f"scope matches on any element (§5.3, F8)")
    _print_sections(stitched, plan)
    if until == "stitch":
        return _assertions(args, source, doc, probed, plan, keys, extraction=extraction,
                           derivation=derivation, stitched=stitched)

    # ── 09 embedding + 10 indexing + 11 gates and publish ────────────────────────────────────
    return _embed_and_index(args, cfg, handle, source=source, doc=doc, probed=probed, plan=plan,
                            keys=keys, facts=facts, extraction=extraction,
                            derivation=derivation, stitched=stitched)


def _offset_blocked(args: argparse.Namespace, cfg: Any, handle: _RunHandle, *, doc: Any,
                    probed: Any, plan: Any, keys: Sequence[str], extraction: Any,
                    failure: Exception) -> bool:
    """An offset failure the ladder could not repair: record it, gate the run, publish nothing.

    The failing window is written to its own control point with ``offset_ok=False``, so §11.1's
    `offset_check` gate reads it the way it reads every other window — the gate's blocking path is
    the pipeline's, not only a test's. With no derived records `window_coverage` blocks too, which
    is honest: nothing was derived.
    """
    details = getattr(failure, "details", {})
    span = tuple(details.get("window") or ())
    print(f"\n   §6.4 REFUSED {details.get('check', OFFSET_CHECK_UNKNOWN)}: {failure}")
    if handle.client is None or handle.record is None:
        raise failure

    for window, key in zip(plan.windows, keys):
        ok = (window.start, window.end) != (span[0], span[1]) if len(span) == 2 else True
        run_module.note_window(handle.client, cfg.runs_collection, run_module.WindowState(
            run_id=handle.record.run_id, doc_id=doc.doc_id, start=window.start, end=window.end,
            state=run_module.DONE if ok else run_module.FAILED, attempts=1, checkpoint="derive",
            extract_key=key, pages_returned=0, offset_ok=ok,
            check=str(details.get("check", "")) if not ok else "",
            detail="" if ok else str(failure)[:500]))

    report = gates_module.evaluate(
        records=[], page_count=probed.page_count,
        windows=[state.outcome() for state in
                 run_module.windows(handle.client, cfg.runs_collection, handle.record.run_id)])
    handle.record = run_module.save(handle.client, cfg.runs_collection, handle.record.model_copy(
        update={"state": run_module.GATED, "step": "derive",
                "gate_results": report.as_dict(), "lease": run_module.Lease()}))
    _log.error("ingest_gated", run_id=handle.record.run_id, step="derive",
               blocked_by=list(report.blocking()), reason=getattr(failure, "code", "offset"),
               window=list(span), queryable=0)
    print(f"   run {handle.record.run_id} is state {handle.record.state}: "
          f"{list(report.blocking())} block it, and 0 page(s) of {doc.doc_id}@{doc.revision} are "
          f"queryable (I7). §6.2's ladder bisects and re-bills; it does not pad and it does not "
          f"guess the offset")
    return False


def _embed_and_index(args: argparse.Namespace, cfg: Any, handle: _RunHandle, *, source: Path,
                     doc: Any, probed: Any, plan: Any, keys: tuple[str, ...], facts: Any,
                     extraction: Any, derivation: Any, stitched: Any) -> bool:
    """Steps 09-11 of §6.1, over the one Qdrant connection the run opened at step 01.

    The connection belongs to the run rather than to a step, because four things need it and none
    of them owns it: the control plane writes the run and window points from step 01 onward, step
    09 reads the embedding cache off the index (register B5), step 10 writes to it, and step 11
    flips and retires. It is closed by the caller in a ``finally``, so a refusal — a fingerprint
    mismatch above all — leaves no socket and no partial write behind.
    """
    _step("09", "embedding — one page, one fused vector, and the receipt that avoids the re-bill")
    backend = embed_module.embedder(cfg)
    collection = cfg.pages_collection
    fingerprint = fingerprint_module.Fingerprint.of(cfg)
    print(f"   backend      {backend.name}  (VSIR_VLM={cfg.vlm} selects the embedding backend too: "
          f"one switch for 'does this release spend')")
    print(f"   model        {backend.model} · dim {backend.dim} · "
          f"composition {COMPOSITION_VERSION} · task_type is never sent (D4)")
    print(f"   fingerprint  {fingerprint.digest}  {fingerprint.as_dict()}")

    client = handle.client
    try:
        state = index_module.ensure_collection(
            client, name=collection, dim=cfg.embed_dim, fingerprint=fingerprint,
            runs_collection=cfg.runs_collection)
        cached = index_module.cached_vectors(
            client, collection, (page.page_id for page in stitched.pages))
    except (fingerprint_module.FingerprintMismatch, index_module.IndexRefused):
        raise
    except Exception as failure:  # noqa: BLE001 - anything else here is the store being down
        raise IngestRefused("qdrant_unavailable",
                            f"{scrub_url(cfg.qdrant_url)}: {type(failure).__name__}: {failure}",
                            qdrant_url=scrub_url(cfg.qdrant_url)) from failure
    print(f"   collection   {collection} ({'created' if state.created else 'existing'}) · "
          f"control plane {cfg.runs_collection} · the §6.6 fingerprint is settled BEFORE a "
          f"single vector is bought")

    embedding = embed_module.embed_document(
        backend, stitched.pages, source=source, content_hash=probed.content_hash,
        doc_title=facts.title, text_chars=cfg.embed_text_chars, cached=cached)
    _log.info("ingest_step", step="embed", backend=backend.name, model=backend.model,
              dim=backend.dim, pages=len(embedding.records), reused=len(embedding.reused),
              billed=len(embedding.billed), text_dropped=embedding.text_dropped,
              collection=collection, fingerprint=fingerprint.digest)
    print(f"   {len(embedding.records)} page(s) · {len(embedding.billed)} embedded, "
          f"{len(embedding.reused)} reused from the index by embed_key (register B5) · "
          f"{embedding.text_dropped} character(s) of page text dropped by the "
          f"{cfg.embed_text_chars}-char cap, counted rather than silently cut")
    _print_composition(embedding, cfg)
    if args.until == "embed":
        return _assertions(args, source, doc, probed, plan, keys, extraction=extraction,
                           derivation=derivation, stitched=stitched, embedding=embedding)

    # ── 10 indexing ──────────────────────────────────────────────────────────────────────
    _step("10", "indexing — one point per page, three surfaces, every one is_current=False")
    written = index_module.upsert(client, collection, embedding.records, embedding.vectors,
                                  fingerprint=fingerprint,
                                  runs_collection=cfg.runs_collection)
    _log.info("ingest_step", step="index", collection=written.collection,
              points=written.count, with_lexical=written.with_lexical,
              with_captions=written.with_captions, is_current=False)
    print(f"   {written.count} point(s) upserted into {written.collection} · "
          f"{written.with_lexical} carry the `lexical` surface · {written.with_captions} carry "
          f"`captions`, which impl declares, weights 0.4 and never writes (register D3)")
    print(f"   {'page_id':<26} {'is_current':<11} point_id = uuid5(NAMESPACE_URL, page_id)")
    for page_id, point in written.points:
        print(f"   {page_id:<26} {'false':<11} {point}")
    print("   nothing is queryable yet: step 11 is the only thing that flips is_current, and "
          "every tool injects is_current=True server-side (I7, §6.7)")
    passed = _assertions(args, source, doc, probed, plan, keys, extraction=extraction,
                         derivation=derivation, stitched=stitched, embedding=embedding,
                         written=written, client=client)
    if args.until == "index":
        return passed

    # ── 11 gates and publish ─────────────────────────────────────────────────────────────
    return _gate_and_publish(args, cfg, handle, doc=doc, probed=probed,
                             derivation=derivation, written=written,
                             records=embedding.records, embedding=embedding) and passed


def _gate_and_publish(args: argparse.Namespace, cfg: Any, handle: _RunHandle, *, doc: Any,
                      probed: Any, derivation: Any, written: Any, records: Sequence[Any],
                      embedding: Any = None) -> bool:
    """Step 11 of §6.1 — the five gates of §11.1, then the publish flip and retirement (§6.7).

    Prints the gate table before it acts, because the gates are the reviewable part: a document
    held here is held for a named reason with its worst pages listed, and a document published is
    published with every number that decided it on screen.
    """
    _step("11", "gates and publish — the only thing that flips is_current, and it flips nothing "
                "until the gates pass")
    client, collection = handle.client, cfg.pages_collection
    window_states = run_module.windows(client, cfg.runs_collection, handle.record.run_id)
    report = gates_module.evaluate(
        records=records, page_count=probed.page_count,
        windows=[state.outcome() for state in window_states], document=derivation.health)

    print(f"   {'gate':<17}{'verdict':<10}{'metric':>9}  detail")
    for result in report.results:
        verdict = ("SKIPPED" if result.skipped else
                   ("PASS" if result.passed else ("BLOCK" if result.blocking else "FLAG")))
        metric = "—" if result.metric is None else f"{result.metric:.4g}"
        print(f"   {result.name:<17}{verdict:<10}{metric:>9}  "
              f"{'blocking' if result.blocking else 'disclosing'}")
        print(f"                     {result.detail}")
        for row in result.evidence[:5]:
            print(f"                     · {row}")

    handle.record = run_module.save(client, cfg.runs_collection, handle.record.model_copy(
        update={"step": "gates", "gate_results": report.as_dict(),
                "pages_indexed": written.count,
                "cost": run_module.Cost(
                    embeddings_billed=len(getattr(embedding, "billed", ()) or ()),
                    embeddings_reused=len(getattr(embedding, "reused", ()) or ()),
                    vlm_calls=sum(1 for state in window_states if state.attempts),
                    cache_hits=len(getattr(embedding, "reused", ()) or ()))}))

    for gate in args.override or ():
        try:
            handle.record = run_module.override(handle.record, gate=gate, reason=args.reason,
                                                by=_owner())
        except gates_module.OverrideRefused as refusal:
            raise IngestRefused(refusal.code, str(refusal), **refusal.details) from refusal
    if args.override:
        handle.record = run_module.save(client, cfg.runs_collection, handle.record)

    try:
        handle.record = run_module.publish(
            client, runs_collection=cfg.runs_collection, collection=collection,
            record=handle.record, report=report, records=list(records), by=_owner())
    except run_module.GateBlocked as blocked:
        queryable = index_module.count(client, collection, {
            "doc_id": doc.doc_id, "revision": doc.revision, "is_current": True})
        print(f"\n   HELD     {list(blocked.details.get('blocked_by', ()))} — "
              f"{queryable} page(s) of {doc.doc_id}@{doc.revision} are queryable (I7)")
        print(f"   release it with: vsir publish {handle.record.run_id} --override "
              f"{gates_module.GROUNDED_RATE} --reason \"<why>\"")
        _log.warning("ingest_gated", run_id=handle.record.run_id,
                     blocked_by=list(blocked.details.get("blocked_by", ())), queryable=queryable)
        return False

    _log.info("ingest_step", step="publish", run_id=handle.record.run_id,
              state=handle.record.state, pages_indexed=handle.record.pages_indexed,
              flags=handle.record.flags, **handle.record.retired)
    print(f"\n   state        {handle.record.state} at {handle.record.published_at}")
    print(f"   pages        {handle.record.pages_indexed} point(s) of {doc.doc_id}@{doc.revision} "
          f"are is_current=True — and {probed.page_count} is the PDF's page count (I1)")
    print(f"   flags        {handle.record.flags or '—'}")
    print(f"   overrides    {[o.gate for o in handle.record.overrides] or '—'}")
    print(f"   retirement   {handle.record.retired} — clause 1 deletes the SAME "
          f"(doc_id, revision) from an earlier run (F12); clause 2 demotes the other revision "
          f"and KEEPS it (F9); clause 3 never touches another document")
    print(f"   exports      GET /runs/{handle.record.run_id}/export/labels.jsonl and "
          f"/observed_tokens.jsonl — streamed from the index, 0 bytes written to disk (§6.8)")
    return _publish_assertions(args, cfg, handle, doc=doc, probed=probed, written=written)


def _publish_assertions(args: argparse.Namespace, cfg: Any, handle: _RunHandle, *, doc: Any,
                        probed: Any, written: Any) -> bool:
    """Step 11's rows, read back out of Qdrant — I1 and I7 as a tool would see them."""
    client, collection = handle.client, cfg.pages_collection
    print("")
    current = index_module.count(client, collection,
                                 {"doc_id": doc.doc_id, "revision": doc.revision,
                                  "is_current": True})
    passed = _check(f"{probed.page_count} page(s) queryable after publish, one per PDF page (I1)",
                    f"count(doc_id={doc.doc_id}, revision={doc.revision}, is_current=True) = "
                    f"{current}",
                    current == probed.page_count == written.count)

    unique = len(set(written.page_ids))
    passed &= _check("every page_id is unique, so one page is one point (I1)",
                     f"{unique} distinct page_id(s) over {written.count} point(s)",
                     unique == written.count)

    stored = run_module.require(client, cfg.runs_collection, handle.record.run_id)
    passed &= _check("the run record is in the control plane, not in this process (D9, E2)",
                     f"{cfg.runs_collection} holds run {stored.run_id}: state {stored.state}, "
                     f"step {stored.step}, {len(stored.gate_results)} gate result(s), lease "
                     f"released ({stored.lease.owner or 'none'})",
                     stored.state == run_module.PUBLISHED and len(stored.gate_results) == len(
                         gates_module.GATES) and not stored.lease.live())

    lines = list(export_module.labels(client, collection, run_id=stored.run_id,
                                      doc_id=doc.doc_id, revision=doc.revision,
                                      safety_doc_types=cfg.safety_doc_types,
                                      safety_topics=cfg.safety_topics))
    fields = sorted(json.loads(lines[0]))  if lines else []
    passed &= _check("labels.jsonl streams one line per page with the §6.8 field set",
                     f"{len(lines)} line(s), fields {fields}",
                     len(lines) == probed.page_count
                     and fields == sorted(export_module.LABEL_FIELDS))

    tokens = list(export_module.observed_tokens(client, cfg.runs_collection,
                                                run_id=stored.run_id, doc_ids=[doc.doc_id]))
    inventory = json.loads(tokens[0]) if tokens else {}
    passed &= _check("observed_tokens.jsonl streams one line per document (§6.8, C7)",
                     f"{len(tokens)} line(s); {inventory.get('token_count', 0)} code-like token(s) "
                     f"observed over {inventory.get('pages', 0)} searchable page(s)",
                     len(tokens) == 1 and inventory.get("doc_id") == doc.doc_id)
    return passed


def _print_composition(embedding: Any, cfg: Any) -> None:
    """The §5.3 part order, on the page that exercises most of it.

    Printed for the page with the most parts rather than page 1, because the order is the clause
    under review and a cover page has no sections, no codes and often no text.
    """
    if not embedding.compositions:
        return
    richest = max(embedding.compositions, key=lambda item: (len(item.parts), item.page_id))
    print(f"\n   the composed Content for {richest.page_id} — {len(richest.parts)} text Part(s), "
          f"then the raster, all in ONE types.Content (D4, D8)")
    print(f"   {'#':<3} {'chars':>6}  part")
    for number, part in enumerate(richest.parts, start=1):
        flat = " ".join(part.split())
        print(f"   {number:<3} {len(part):>6}  "
              f"{flat[:64] + ('…' if len(flat) > 64 else '')!r}")
    print(f"   {len(richest.parts) + 1:<3} {len(richest.image):>6}  the page raster @ dpi "
          f"{richest.dpi} (dpi_index), long edge bounded to "
          f"{embed_module.EMBED_MAX_EDGE_PX} px — the LAST Part")
    print(f"   {richest.summary_parts} summary Part(s), one per language: a two-language page is "
          f"never one blended string (D5, D8)")
    print(f"   embed_key    {_short(richest.key(embedding.model), 24)}  "
          f"(composition version ‖ {embedding.model} ‖ the composed string)")


def _observed(derivation: Any) -> int:
    """How many pages check (2) actually had evidence for — a label and a text layer to check it
    against. Printed rather than implied, because a check that silently applied to nothing would
    read exactly like a check that passed."""
    return sum(1 for page in derivation.pages
               if page.record.has_text and page.record.content.printed_page_no)


def _print_derived(derivation: Any) -> None:
    """The per-page derivation table — the unit's Working Deliverable."""
    print()
    print(f"   {'page':>4}  {'page_id':<28} {'label':<6} {'ver':<4} {'grounded':>8}  "
          f"{'codes':>5} {'in_text':>7}  moved_from / flags")
    for page in derivation.pages:
        record = page.record
        rate = "—" if record.content.grounded_rate is None else f"{record.content.grounded_rate:.2f}"
        moved = " ".join(f"{m.code}<-{m.from_page_id.rsplit('#', 1)[-1]}"
                         for m in record.content.moved_from)
        notes = " ".join(filter(None, [moved, ",".join(record.content.flags)]))
        print(f"   {record.page_no:>4}  {record.provenance.page_id:<28} "
              f"{record.content.printed_page_no or '—':<6} "
              f"{str(record.content.label_verified).lower():<4} {rate:>8}  "
              f"{len(record.content.codes):>5} {len(record.content.codes_in_text):>7}  {notes}")


def _print_sections(stitched: Any, plan: Any) -> None:
    """The section table, and the folds each section survived."""
    folds = [window.end for window in plan.windows[:-1]]
    print()
    print(f"   {'section_id':<28} {'pages':<9} {'start':>5} {'obs':>4}  {'folds':<7} "
          f"series_id / title")
    for section in stitched.sections:
        low, high = section.page_range
        crossed = [fold for fold in folds if low <= fold < high]
        print(f"   {section.section_id:<28} {f'{low}-{high}':<9} {section.start_page:>5} "
              f"{len(section.pages):>4}  {str(crossed) if crossed else '—':<7} "
              f"{section.series_id}  \"{section.title}\"")
    for section in stitched.sections:
        low, high = section.page_range
        crossed = [fold for fold in folds if low <= fold < high]
        if not crossed:
            continue
        pages = [record for record in stitched.pages
                 if section.section_id in record.section_id]
        print(f"   \"{section.title}\" crosses the window fold at {crossed[0]}|{crossed[0] + 1} "
              f"and carries ONE section_id on all {len(pages)} of its pages: "
              f"{[record.page_no for record in pages]}")


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
                plan: Any, keys: tuple[str, ...], *, extraction: Any,
                derivation: Any = None, stitched: Any = None, embedding: Any = None,
                written: Any = None, client: Any = None) -> bool:
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
    if derivation is not None:
        passed &= _derivation_assertions(table, probed, extraction, derivation)
    if stitched is not None:
        passed &= _stitch_assertions(table, plan, stitched)
    if embedding is not None:
        passed &= _embed_assertions(table, embedding, load_config())
    if written is not None and client is not None:
        passed &= _index_assertions(table, embedding, written, client, written.collection,
                                    load_config())
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


def _derivation_assertions(table: dict, probed: Any, extraction: Any,
                           derivation: Any) -> bool:
    """Step 07's rows: I2's provenance, the offset proof, the `None`, and the two code traps."""
    records = {page.page_no: page.record for page in derivation.pages}
    texts = derive_module.probe_texts(probed)

    # I2, and the assertion §12.5 names as its real enforcement — the grep cannot see this.
    mismatched = [page_no for page_no, record in records.items()
                  if record.text != texts[page_no]]
    passed = _check("every record's `text` is the probe's, character for character (I2, §12.5)",
                    f"{len(records) - len(mismatched)}/{len(records)} pages match "
                    f"probe_text[page_no]; ingest/probe.py is the only writer",
                    not mismatched)

    ids_ok = all(record.provenance.page_id == ids.page_id(record.doc_id, record.revision, page_no)
                 for page_no, record in records.items())
    passed &= _check("abs_page == window.start + page_index - 1 on every emitted page (§6.4)",
                    f"pages {min(records)}-{max(records)}, {len(records)} record(s), each "
                    f"page_id built from its own absolute page",
                    sorted(records) == list(range(1, probed.page_count + 1)) and ids_ok)

    # §6.4 check (2), armed: shift one window by a page and the model's own labels give it away.
    shifted = extraction.windows[1] if len(extraction.windows) > 1 else extraction.windows[0]
    moved = dataclasses.replace(
        shifted, window=window_module.Window(shifted.window.start + 1, shifted.window.end + 1,
                                             shifted.window.level))
    try:
        derive_module.check_offset(moved, probed)
        caught: Any = None
    except derive_module.OffsetError as refusal:
        caught = refusal
    passed &= _check("the off-by-one trap: a window shifted by one page is caught by the "
                    "independent observation, not by luck (I4, F7)",
                    (f"window {shifted.window.start}-{shifted.window.end} shifted to "
                     f"{moved.window.start}-{moved.window.end} raises {caught.code}: label "
                     f"\"{caught.details['label']}\" is printed on page "
                     f"{caught.details['printed_on']}, not on {caught.details['page_no']}"
                     if caught else "no OffsetError was raised — the check is not armed"),
                    caught is not None
                    and caught.details.get("check") == "independent_observation")

    without = table["pages_without_text"]
    none_rated = sorted(page_no for page_no, record in records.items()
                       if record.content.grounded_rate is None)
    passed &= _check("grounded_rate is None exactly where has_text is false, and the median "
                    "ignores those pages (§5.7)",
                    f"pages {none_rated} rate None; the median over the remaining "
                    f"{derivation.health.pages_with_text} is "
                    f"{derivation.health.grounded_median}",
                    none_rated == without and derivation.health.grounded_median is not None)

    labels = {str(page_no): record.content.printed_page_no
              for page_no, record in records.items()}
    verified = sum(1 for record in records.values() if record.content.label_verified)
    passed &= _check("every printed label is the one the page carries, and none was picked "
                    "silently (§6.5, F5)",
                    f"{verified}/{len(records)} labels confirmed against the page itself; "
                    f"0 ambiguous, 0 interpolated",
                    labels == table["printed_labels"]
                    and not any(record.content.label_candidates
                                for record in records.values()))

    trap = table["extraction"]["reattribution"]
    receiver = records[trap["from_page"]]
    donor = records[trap["page"]]
    origin = ids.page_id(doc_id := receiver.doc_id, receiver.revision, trap["page"])
    passed &= _check("the reattributed code moved to the page whose text prints it, and said "
                    "where it came from (F6)",
                    f"{trap['code']} left page {trap['page']} and arrived on "
                    f"{trap['from_page']} as "
                    f"{[m.model_dump() for m in receiver.content.moved_from]}",
                    [m.model_dump() for m in receiver.content.moved_from]
                    == [{"code": trap["code"], "from_page_id": origin}]
                    and trap["code"] not in donor.content.codes)

    loose = table["extraction"]["ungrounded"]
    stayed = records[loose["page"]]
    passed &= _check("the ungrounded code stayed put, cost its page grounded_rate, and is in no "
                    "page's codes_in_text (I2, F14)",
                    f"{loose['code']} is still on page {loose['page']}, whose grounded_rate is "
                    f"{stayed.content.grounded_rate:.3f}; it appears in "
                    f"{sum(1 for r in records.values() if loose['code'].lower() in r.content.codes_in_text)} "
                    f"codes_in_text list(s) and {sum(1 for r in records.values() if loose['code'] in r.text)} "
                    f"page text(s)",
                    loose["code"] in stayed.content.codes
                    and stayed.content.grounded_rate < 1.0
                    and not any(loose["code"].lower() in record.content.codes_in_text
                                for record in records.values()))
    return passed


def _stitch_assertions(table: dict, plan: Any, stitched: Any) -> bool:
    """Step 08's rows: one section per canonical key, and the folds gone (F8)."""
    observed = [{"first": section.page_range[0], "last": section.page_range[1],
                 "title": section.title} for section in stitched.sections]
    passed = _check(f"{len(table['sections'])} sections with the extent the fixture declares",
                   f"{len(stitched.sections)} section(s): "
                   + " · ".join(f"{s['first']}-{s['last']}" for s in observed),
                   observed == table["sections"])

    folds = [window.end for window in plan.windows[:-1]]
    straddling = {section.title: section for section in stitched.sections
                  if any(section.page_range[0] <= fold < section.page_range[1]
                         for fold in folds)}
    passed &= _check("a section cut by a window fold is ONE section, on both sides (F8)",
                    f"{sorted(straddling)} cross the fold(s) at {folds}; each has one "
                    f"section_id over pages "
                    + " · ".join(f"{s.page_range[0]}-{s.page_range[1]}"
                                 for s in straddling.values()),
                    sorted(straddling) == sorted(table["straddling_sections"]))

    carried = all(
        {record.section_id[0] for record in stitched.pages
         if section.page_range[0] <= record.page_no <= section.page_range[1]} == {section.section_id}
        for section in straddling.values()
    )
    passed &= _check("every page of a straddling section carries the same section_id, as an "
                    "array (§5.3)",
                    f"one id across each fold; series_id "
                    f"{[s.series_id for s in straddling.values()]} carries no revision, so a "
                    f"scope on it survives one (F8, U025)",
                    carried and all("@" not in section.series_id
                                    for section in stitched.sections))
    return passed


def _embed_assertions(table: dict, embedding: Any, cfg: Any) -> bool:
    """Step 09's rows: the composition is §5.3's, and one page is one vector.

    These are structural, not baselined: each one recomputes the property from the spec's own
    statement of it rather than comparing against a number the fixture recorded, which is the only
    honest way to assert an order and a count (the dim and the page count still come from
    configuration and from the table).
    """
    pages = table["page_count"]
    passed = _check(f"one page, one fused vector — {pages} pages, {pages} vectors (I1, D4)",
                    f"{len(embedding.compositions)} composition(s), "
                    f"{len(embedding.vectors)} vector(s), dim "
                    f"{sorted({len(v) for v in embedding.vectors.values()})}",
                    len(embedding.compositions) == pages
                    and len(embedding.vectors) == pages
                    and {len(v) for v in embedding.vectors.values()} == {cfg.embed_dim})

    with_text = [item for item in embedding.compositions if item.text_chars]
    passed &= _check("every text part is its own Part, and the raster is the last one (D4, D8)",
                    f"{sum(len(i.parts) for i in embedding.compositions)} text Part(s) over "
                    f"{len(embedding.compositions)} page(s); {len(with_text)} carry page text, "
                    f"and every composition ends with the dpi {DPI_INDEX} raster",
                    all(item.dpi == DPI_INDEX and item.image for item in embedding.compositions)
                    and all(part.strip() for item in embedding.compositions
                            for part in item.parts))

    keys = {item.page_id: item.key(embedding.model) for item in embedding.compositions}
    passed &= _check("embed_key is per composition, so an unchanged page is free next run (B5)",
                    f"{len(set(keys.values()))} distinct key(s) for {len(keys)} page(s); "
                    f"{len(embedding.reused)} reused this run",
                    len(set(keys.values())) == len(keys)
                    and all(record.provenance.embed_key == keys[record.page_id]
                            for record in embedding.records))
    return passed


def _unit(vector: Sequence[float]) -> list[float]:
    """``vector`` as Qdrant stores it in a cosine collection: normalised to unit length."""
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


def _index_assertions(table: dict, embedding: Any, written: Any, client: Any,
                      collection: str, cfg: Any) -> bool:
    """Step 10's rows, read back **out of Qdrant** — the payload a tool would see, not our copy."""
    import uuid as _uuid

    pages = table["page_count"]
    passed = _check(f"{pages} point(s) written, one per page (I1)",
                    f"{written.count} upserted into {collection}",
                    written.count == pages)

    expected = {page_id: str(_uuid.uuid5(_uuid.NAMESPACE_URL, page_id))
                for page_id, _ in written.points}
    passed &= _check("point_id == uuid5(NAMESPACE_URL, page_id), recomputed independently (§5.1)",
                    f"{sum(1 for p, q in written.points if expected[p] == q)}/{written.count} "
                    f"match; a re-ingest therefore overwrites rather than doubling (F12)",
                    all(expected[page_id] == point for page_id, point in written.points))

    stored = client.retrieve(collection, ids=list(written.point_ids), with_payload=True,
                             with_vectors=True)
    payloads = {(point.payload or {}).get("provenance", {}).get("page_id"): point
                for point in stored}
    passed &= _check("every point is is_current=False until the gates pass (I7, §6.7)",
                    f"{sum(1 for p in stored if (p.payload or {}).get('is_current') is False)}"
                    f"/{len(stored)} read back false",
                    len(stored) == pages
                    and all((point.payload or {}).get("is_current") is False for point in stored))

    named = sorted({key for point in stored
                    for key in index_module.FORBIDDEN_PAYLOAD_KEYS if key in (point.payload or {})})
    passed &= _check("no payload names a file — there is no image_path (§5.3, register A5)",
                    f"forbidden keys present in {len(stored)} payload(s): {named or 'none'}",
                    not named)

    # Two facts about how Qdrant stores a cosine vector, and the check has to know both or it
    # fails on a truth rather than on a defect. It **normalises** on write, because cosine
    # similarity of unit vectors is a dot product — so the round trip preserves the direction and
    # not the magnitude. And it keeps float32, so a component comes back about 1e-9 from the
    # float64 that went in — which is why this is a tolerance and not a rounded equality: over
    # 1,536 components, some value always lands next to a rounding boundary.
    dense = {page_id: (point.vector or {}).get("dense") for page_id, point in payloads.items()}
    drift = max((max(abs(a - b) for a, b in zip(vector, _unit(embedding.vectors[page_id])))
                 for page_id, vector in dense.items() if vector is not None), default=1.0)
    sized = sum(1 for vector in dense.values()
                if vector is not None and len(vector) == cfg.embed_dim)
    passed &= _check("the stored dense vector is the one step 09 composed, unchanged",
                    f"{sized}/{pages} vectors of dim {cfg.embed_dim} read back; largest component "
                    f"drift {drift:.2e} — float32 storage, not a different vector",
                    sized == pages and drift <= VECTOR_STORAGE_TOLERANCE)

    generated = [record for record in embedding.records
                 if record.content.summaries or record.content.topics]
    carried = [point for page_id, point in payloads.items()
               if index_module.CAPTIONS in (point.vector or {})]
    shared = {token
              for record in generated
              for token in tok(index_module.caption_text(record))
              if token in token_set(record.text)}
    passed &= _check("the `captions` surface is written, and shares no token with `lexical` (D3)",
                    f"{len(carried)}/{len(generated)} page(s) with summaries or topics carry a "
                    f"non-empty captions vector; dedupe(against=text) left {len(shared)} "
                    f"already-printed token(s) in it",
                    len(carried) == len(generated) and not shared)

    again = index_module.upsert(client, collection, embedding.records, embedding.vectors,
                                fingerprint=fingerprint_module.Fingerprint.of(cfg),
                                runs_collection=cfg.runs_collection)
    total = index_module.count(client, collection,
                               {"doc_id": embedding.records[0].doc_id,
                                "revision": embedding.records[0].revision})
    passed &= _check("re-running the same write overwrites in place: the count is unchanged (I1)",
                    f"upserted {again.count} again, and the collection still holds {total} "
                    f"point(s) for this (doc_id, revision)",
                    again.count == pages and total == pages)
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

    # A resumed run keeps its own id, because the id is what every point of the run carries: a
    # resume under a fresh id would write a second set of points that publish's filter could not
    # find and retirement would delete as stale (§6.7).
    identifier = args.resume or ids.run_id()
    handle = _RunHandle(runs_collection=cfg.runs_collection)
    with vsir_logging.correlate(run_id=identifier):
        print(f"vsir ingest — release {cfg.release_id} · run {identifier} · until {args.until}")
        _log.info("ingest_started", pdf=str(args.pdf), until=args.until, vlm=cfg.vlm,
                  vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version, dpi=DPI_ANSWER,
                  resume=bool(args.resume), steal=bool(args.steal))
        if args.until in STORE_BACKED_STEPS:
            try:
                handle.client = _open_store(cfg)
            except IngestRefused as refusal:
                _log.error("ingest_refused", reason=refusal.code, detail=str(refusal),
                           **refusal.details)
                print(f"\n   REFUSED  {refusal.code}: {refusal}")
                return EXIT_REFUSED
        previous = _install_drain(handle)
        try:
            passed = _ingest(args, cfg, handle)
        except (IngestRefused, window_module.WindowError, render.RenderError,
                embed_module.EmbedError, fingerprint_module.FingerprintMismatch,
                index_module.IndexRefused, run_module.RunRefused) as refusal:
            _log.error("ingest_refused", reason=refusal.code, detail=str(refusal),
                       **getattr(refusal, "details", {}))
            print(f"\n   REFUSED  {refusal.code}: {refusal}")
            _record_failure(handle, cfg, reason=refusal.code, detail=str(refusal))
            return EXIT_REFUSED
        except FileNotFoundError as refusal:
            _log.error("ingest_refused", reason="source_missing", detail=str(refusal))
            print(f"\n   REFUSED  source_missing: {refusal}")
            _record_failure(handle, cfg, reason="source_missing", detail=str(refusal))
            return EXIT_REFUSED
        finally:
            signal.signal(signal.SIGTERM, previous)
            if handle.client is not None:
                handle.client.close()
        _log.info("ingest_complete", until=args.until, passed=passed)
    print(f"\n{'ALL ASSERTIONS PASSED' if passed else 'ASSERTIONS FAILED'}")
    return EXIT_OK if passed else EXIT_REFUSED


def _install_drain(handle: _RunHandle) -> Any:
    """Replace the process-wide SIGTERM handler with one that checkpoints this run (§15 IX).

    A closure over the handle rather than anything module-level, and the previous handler is
    returned so the caller restores it: an ingest that has finished must not leave a handler
    holding a closed client. What the handler does is small on purpose — mark the run `stopped`
    and exit. It publishes nothing, so a kill loses at most the windows since the last checkpoint
    and **never** leaves a queryable half-document (I7, F17).
    """

    def _on_sigterm(signum: int, _frame: FrameType | None) -> None:
        _log.info("sigterm", signal=signum, action="checkpoint_and_exit",
                  run_id=getattr(handle.record, "run_id", ""))
        handle.stopped()
        raise SystemExit(EXIT_OK)

    return signal.signal(signal.SIGTERM, _on_sigterm)


def _record_failure(handle: _RunHandle, cfg: Any, *, reason: str, detail: str) -> None:
    """Write the refusal onto the run point, so a failed run says which step failed and why.

    Best effort by necessity: the most likely reason a run failed is that the store did not
    answer, and a failure to record a failure must not replace the operator's error message with
    a different one.
    """
    if handle.client is None or handle.record is None:
        return
    if handle.record.state in (run_module.GATED, run_module.PUBLISHED):
        # A gate already judged this run and named the gate that blocked it. Overwriting that with
        # `failed` would replace the reason with a category (§6.9).
        return
    try:
        run_module.fail(handle.client, cfg.runs_collection, handle.record,
                        step=handle.record.step, reason=reason, detail=detail)
    except Exception as failure:  # noqa: BLE001 — see the docstring
        _log.warning("run_failure_unrecorded", reason=reason,
                     detail=f"{type(failure).__name__}: {failure}")


# ── `vsir runs show` · `vsir gates rerun` · `vsir publish` (§4.4) ─────────────────────────────────

def _with_store(handler: Any) -> Any:
    """Load the configuration, open one Qdrant connection, close it however the command ends."""

    def run(args: argparse.Namespace) -> int:
        try:
            cfg = load_config()
        except ConfigError as refusal:
            _log.error("command_refused", reason="configuration", detail=str(refusal))
            print(f"   configuration refused: {refusal}")
            return EXIT_REFUSED
        try:
            client = _open_store(cfg)
        except IngestRefused as refusal:
            _log.error("command_refused", reason=refusal.code, detail=str(refusal))
            print(f"   REFUSED  {refusal.code}: {refusal}")
            return EXIT_REFUSED
        try:
            return handler(args, cfg, client)
        except (run_module.RunRefused, gates_module.OverrideRefused,
                export_module.ExportRefused) as refusal:
            _log.error("command_refused", reason=refusal.code, detail=str(refusal),
                       **getattr(refusal, "details", {}))
            print(f"   REFUSED  {refusal.code}: {refusal}")
            return EXIT_REFUSED
        finally:
            client.close()

    return run


def _print_run(record: Any) -> None:
    """The run record of §6.9, every field of it. What `GET /runs/{run_id}` returns, printed."""
    print(f"run          {record.run_id}")
    print(f"document     {record.doc_id}@{record.revision} · release {record.release_id} · "
          f"schema {record.schema_version}")
    print(f"state        {record.state} · step {record.step or '—'} · "
          f"windows {record.windows_done}/{record.windows_total} · "
          f"pages_indexed {record.pages_indexed} of {record.page_count}")
    print(f"lease        {record.lease.owner or '—'} until {record.lease.expires_at or '—'} "
          f"({'live' if record.lease.live() else 'not live'})")
    print(f"published_at {record.published_at or '—'} · flags {record.flags or '—'}")
    print(f"cost         {record.cost.model_dump()}")
    if record.failed:
        print(f"failed       step {record.failed.step}: {record.failed.reason} "
              f"— {record.failed.detail}")
    if record.retired:
        print(f"retired      {record.retired}")
    for override in record.overrides:
        print(f"override     {override.gate} by {override.by} at {override.at}: "
              f"\"{override.reason}\"")
    print(f"\n{'gate':<17}{'verdict':<10}{'metric':>9}  detail")
    for name, row in record.gate_results.items():
        verdict = ("SKIPPED" if row.get("skipped") else
                   ("PASS" if row.get("pass") else ("BLOCK" if row.get("blocking") else "FLAG")))
        metric = "—" if row.get("metric") is None else f"{row['metric']:.4g}"
        print(f"{name:<17}{verdict:<10}{metric:>9}  {row.get('detail', '')}")
        for evidence in (row.get("evidence") or [])[:5]:
            print(f"                                    · {evidence}")


def _reevaluate(client: Any, cfg: Any, record: Any) -> Any:
    """Re-run the five gates against what is **in the index** (§11.1).

    Nothing from the ingesting process is used: the records are scrolled back out of the pages
    collection and the window outcomes off the control plane, so `gates rerun` judges the document
    that is actually stored rather than the one a process believed it stored (§15 Factor VI).
    """
    records = run_module.run_records(client, cfg.pages_collection, doc_id=record.doc_id,
                                     revision=record.revision, run_id=record.run_id)
    windows = [state.outcome() for state in
               run_module.windows(client, cfg.runs_collection, record.run_id)]
    page_count = record.page_count or len(records)
    return records, gates_module.evaluate(records=records, page_count=page_count, windows=windows)


def _cmd_runs_show(args: argparse.Namespace, cfg: Any, client: Any) -> int:
    _print_run(run_module.require(client, cfg.runs_collection, args.run_id))
    return EXIT_OK


def _cmd_gates_rerun(args: argparse.Namespace, cfg: Any, client: Any) -> int:
    record = run_module.require(client, cfg.runs_collection, args.run_id)
    _records, report = _reevaluate(client, cfg, record)
    saved = run_module.save(client, cfg.runs_collection,
                            record.model_copy(update={"gate_results": report.as_dict()}))
    _log.info("gates_rerun", run_id=saved.run_id, blocked_by=list(report.blocking(
        saved.overridden)), flags=list(report.flags))
    _print_run(saved)
    blocked = report.blocking(saved.overridden)
    print(f"\nblocked by   {list(blocked) or 'nothing'} · flags {list(report.flags) or 'none'}")
    print("re-evaluated against the index, not against this process: the records were scrolled "
          "back out of the collection and the window outcomes off the control plane")
    return EXIT_OK


# ── `vsir lookup` / `vsir verify` — the one-shot tool calls of §4.4 ─────────────────────────────

#: The process type these one-shots are attributed to in the budget ledger and the audit line.
#: One name for every `vsir <tool>` invocation, because the ceiling is a property of the
#: deployment's admin surface and not of whichever shell happened to run it (§7.4, §15 XII).
CLI_PROCESS = "cli"


def _scope_from(pairs: Sequence[str]) -> dict[str, Any]:
    """``--scope doc_id=SYN-M1 --scope page_no=5`` → a scope dict, values typed as they look.

    No schema here on purpose. `INDEXED` is the schema and `core.exact` refuses a key outside it
    with `filter_unknown_key` (I6, F10), so a second list of legal keys in the CLI would be a
    second source of truth for the one dict that has three jobs (§5.4) — and the one in the CLI
    would be the one that goes stale.

    Values are read with :func:`ast.literal_eval` and fall back to the string, so ``page_no=5``
    filters on the integer the payload actually holds while ``doc_id=SYN-M1`` stays text.
    """
    scope: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key.strip():
            raise ToolError("scope_malformed", f"--scope takes key=value, got {pair!r}",
                            requested=pair)
        try:
            scope[key.strip()] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            scope[key.strip()] = raw
    return scope


def _one_shot(tool: str, arguments: dict[str, Any], *, as_json: bool,
              render: Any) -> int:
    """Run one tool through the **release's own dispatcher** and print what came back.

    This is the whole point of the one-shots. `_run_tool`, the `INDEXED` gate, the budget, the
    typed refusals and `is_current=True` are the serving path's, unchanged and un-bypassed
    (:func:`vsir.serve.app.dispatch`) — so `vsir lookup` is evidence about the shipped tool and
    not about a second, friendlier implementation of it that happens to live in the CLI.

    **A typed absence exits 0.** `lookup("alarm 152")` searched, found nothing, and said so
    correctly: that is a successful call and §7.1's whole argument is that it is not an error.
    Only a refusal — a `400` naming a bound, a `404`, a `503` — is a non-zero exit, which is also
    what makes the §4.4 demo chain with `&&` read the way a reviewer expects.

    **With ``--json``, nothing is printed on stdout but the envelope.** The rule is
    `vsir mcp --stdio`'s and the reason is the same one: under `vsir serve` stdout *is* the event
    stream (§15 Factor XI), and here ``--json`` has declared it the machine surface — so a
    perfectly good ``boot_check_ok`` in front of the body is a parse error at whatever is reading
    it. The stream moves to stderr **before the boot check runs**, so a boot refusal is still
    reported in full; the two outputs are separated, never one of them silenced. Without
    ``--json`` the output is a human rendering and stdout stays the event stream, unchanged.
    """
    if as_json:
        vsir_logging.configure(
            release_id=(os.environ.get("VSIR_RELEASE_ID") or "").strip() or "unknown",
            level=(os.environ.get("VSIR_LOG_LEVEL") or "INFO").strip(),
            stream=sys.stderr)
    try:
        runtime, client = app_module.runtime_from_env(dict(os.environ))
    except BootRefused as refusal:
        _log.error("boot_refused", failed_checks=refusal.failed_checks, detail=str(refusal))
        print(f"   REFUSED  boot: {refusal}")
        return EXIT_REFUSED
    except ConfigError as refusal:
        _log.error("command_refused", reason="configuration", detail=str(refusal))
        print(f"   configuration refused: {refusal}")
        return EXIT_REFUSED

    try:
        outcome = app_module.dispatch(
            runtime, tool, arguments,
            identity=auth_module.local_identity(CLI_PROCESS), correlation={})
    finally:
        client.close()

    if as_json:
        # The bytes an HTTP caller would have received, byte for byte (§7.5), and the only thing
        # on stdout — so `vsir lookup … --json | jq` is reading the wire contract rather than a
        # printed rendering of it. Asserted in tests/api/test_one_shot_parity.py.
        print(outcome.body().decode("utf-8"))
    elif outcome.refused:
        payload = outcome.payload
        print(f"   REFUSED  {outcome.status} {payload.get('error')}: {payload.get('detail')}")
    else:
        render(outcome.payload)
    return EXIT_OK if not outcome.refused else EXIT_REFUSED


def _print_lookup(payload: Mapping[str, Any]) -> None:
    """A `lookup` envelope, printed. Every field a caller switches on is on the first two lines."""
    stats = payload.get("scope_stats") or {}
    print(f"status       {payload['status']} · total {payload['total']} · "
          f"capped {str(payload['capped']).lower()} · weak {str(payload['weak']).lower()} · "
          f"needs_scope {str(payload['needs_scope']).lower()}")
    print(f"scope        {payload['effective_scope']} · searched {stats.get('pages', 0)} page(s), "
          f"{stats.get('pages_no_text', 0)} with no text layer")
    for hit in payload.get("hits") or ():
        print(f"  HIT        {hit['page_id']} · printed {hit['printed_page_no'] or '—'} · "
              f"{hit['page_kind']} · verified {str(hit['verified']).lower()} · "
              f"trust {hit['text_trust']} · image {hit['image']['url'] if hit['image'] else '—'}")
    for hit in payload.get("unverified_hits") or ():
        # Labelled at the point of display, not just in the field: these are `vlm_codes` hits and
        # they are the one thing on this surface that was never printed on a page (D3).
        print(f"  UNVERIFIED {hit['page_id']} · model-claimed, verified "
              f"{str(hit['verified']).lower()} — never evidence")
    moves = payload.get("next") or {}
    if moves.get("suggest"):
        print(f"next         suggest {moves['suggest']} · tokens that did occur "
              f"{moves.get('tokens_observed') or []}")
    print(f"reads_left   {payload['reads_remaining']} · release "
          f"{payload['provenance']['release_id']} · schema "
          f"{payload['provenance']['schema_version']}")


def _print_verify(payload: Mapping[str, Any]) -> None:
    """A `verify` envelope, printed — Family B, so the verdicts are the answer (§7.1)."""
    verdicts = (payload.get("result") or {}).get("claims") or {}
    print(f"status       {payload['status']} — the CALL ran; the verdicts are below "
          f"({len(verdicts)} claim(s))")
    print(f"\n{'claim':<16}{'verdict':<14}pages / why")
    for claim, verdict in verdicts.items():
        detail = ", ".join(verdict.get("page_ids") or ()) or (verdict.get("reason") or "—")
        print(f"{claim:<16}{verdict['status']:<14}{detail}")
        if verdict.get("present_instead"):
            print(f"{'':<30}{PRESENT_INSTEAD_LABEL}: {verdict['present_instead']}")
    print(f"\nreads_left   {payload['reads_remaining']} · release "
          f"{payload['provenance']['release_id']} · schema "
          f"{payload['provenance']['schema_version']}")


def _cmd_lookup(args: argparse.Namespace) -> int:
    try:
        scope = _scope_from(args.scope)
    except ToolError as refusal:
        print(f"   REFUSED  {refusal.code}: {refusal.message}")
        return EXIT_REFUSED
    return _one_shot("lookup", {"label": args.label, "scope": scope,
                                "include_unverified": args.include_unverified, "cap": args.cap},
                     as_json=args.json, render=_print_lookup)


def _cmd_verify(args: argparse.Namespace) -> int:
    return _one_shot("verify", {"claims": _csv_arg(args.claims),
                                "page_ids": _csv_arg(args.pages)},
                     as_json=args.json, render=_print_verify)


def _csv_arg(raw: str) -> list[str]:
    """``"K73, K158"`` → ``["K73", "K158"]``. Order preserved, duplicates left to the tool."""
    return [value.strip() for value in raw.split(",") if value.strip()]


# ── `vsir mcp` (§4.4, §7.5) ─────────────────────────────────────────────────────────────────────

def _cmd_mcp(args: argparse.Namespace) -> int:
    """The MCP surface of §7.5, over whichever transport was asked for.

    ``--sse`` runs **the serving app** — §15 Factor VII pins the SSE transport to the same port
    the HTTP surface binds, so there is no second server to start and this is `vsir serve` under
    the name §4.4 gives it. The distinction the flag makes is which surface a client is being
    pointed at, not which process is running.

    ``--stdio`` is the one-off process (Factor XII): one client on a pipe, no socket, and stdout
    reserved for the protocol.
    """
    if not args.sse:
        # Neither flag means stdio: a bare `vsir mcp` is what an MCP client config spawns, and
        # the transport it can spawn is a pipe. `--sse` is the deliberate one, because it binds
        # a socket.
        try:
            mcp_server.run_stdio(dict(os.environ))
        except BootRefused as refusal:
            _log.error("boot_refused", failed_checks=refusal.failed_checks, detail=str(refusal))
            return EXIT_REFUSED
        except ConfigError as refusal:
            _log.error("boot_refused", failed_checks=["config_valid"], detail=str(refusal))
            return EXIT_REFUSED
        return EXIT_OK
    return _cmd_serve(args)


# ── `vsir serve` (§4.4, §7.4) ────────────────────────────────────────────────────────────────────

#: What the server binds. `0.0.0.0` because the process type this command runs is `web` in a
#: container, where anything else is unreachable (§15 Factor VII); `--host` is there for a laptop.
#: The **port** is not a flag: it is `VSIR_PORT`, because it is configuration (§15 Factor III).
SERVE_HOST = "0.0.0.0"


def _cmd_serve(args: argparse.Namespace) -> int:
    """Bind ``$VSIR_PORT`` and serve §7.4 — after the boot self-check, never before it.

    The app is built **here**, before uvicorn exists, so a §4.3 refusal — a floating model id, a
    live schema that disagrees with `INDEXED`, a missing variable — is a named non-zero exit with
    no socket ever bound. That ordering is the requirement, not an implementation detail: a
    process that binds the port and *then* discovers it cannot serve correctly has already joined
    the load balancer, and §4.3's rule is that it must never degrade to a partial service.

    ``SIGTERM`` is uvicorn's from here on: it stops accepting, drains what is in flight and
    unwinds the lifespan (§15 Factor IX). The CLI's own handler, which exits immediately, is
    replaced for the duration — a server has in-flight work and the ingest pipeline's checkpoint
    is not its concern.

    **This is the one command that prints nothing.** Every other subcommand here is a one-off
    admin process whose stdout a person reads; `serve` runs as the `web` process type, and its
    stdout *is* the event stream a platform collects — where the contract is one JSON object per
    line (§15 Factor XI). A friendly banner would be three lines a log collector cannot parse,
    which is the defect `tests/api/test_log_stream.py` exists to catch.
    """
    import uvicorn  # local: a CLI that only runs `doctor` should not import a web server

    try:
        app = create_app()
    except BootRefused as refusal:
        _log.error("boot_refused", failed_checks=refusal.failed_checks, detail=str(refusal),
                   bound=False)
        return EXIT_REFUSED
    except ConfigError as refusal:
        _log.error("boot_refused", failed_checks=["config_valid"], detail=str(refusal),
                   bound=False)
        return EXIT_REFUSED

    cfg = config_of(app)
    _log.info("serve", host=args.host, port=cfg.port, tools=sorted(app.state.tools),
              free_paths=sorted(auth_module.PUBLIC_PATHS))
    # `log_config=None`: uvicorn's default installs its own dictConfig and its own plain-text
    # formatter, which would make stdout a mixed stream and stop "one JSON object per line" from
    # being true of what the platform collects (§15 Factor XI). `create_app` has already folded
    # uvicorn's loggers into ours.
    uvicorn.run(app, host=args.host, port=cfg.port, log_config=None, access_log=True)
    return EXIT_OK


def _cmd_publish(args: argparse.Namespace, cfg: Any, client: Any) -> int:
    record = run_module.require(client, cfg.runs_collection, args.run_id)
    for gate in args.override or ():
        record = run_module.override(record, gate=gate, reason=args.reason, by=_owner())
    records, report = _reevaluate(client, cfg, record)
    record = run_module.save(client, cfg.runs_collection,
                             record.model_copy(update={"gate_results": report.as_dict()}))
    try:
        published = run_module.publish(client, runs_collection=cfg.runs_collection,
                                       collection=cfg.pages_collection, record=record,
                                       report=report, records=list(records), by=_owner())
    except run_module.GateBlocked as blocked:
        print(f"   HELD     {list(blocked.details.get('blocked_by', ()))} still block "
              f"{record.doc_id}@{record.revision}; zero pages of it are queryable (I7)")
        raise
    _print_run(published)
    flagged = index_module.count(client, cfg.pages_collection, {
        "doc_id": published.doc_id, "revision": published.revision, "is_current": True})
    print(f"\npublished    {flagged} page(s) are is_current=True")
    if published.overrides:
        print(f"every page carries the {gates_module.FLAG_PUBLISHED_WITH_OVERRIDE!r} flag, and "
              f"the reason is on the run record above")
    return EXIT_OK


# ── `vsir eval` — the evaluations of §12.3 and §12.4 (M3; `corpus` is §12.6's, at M8) ────────────

def _cmd_eval_acceptance(args: argparse.Namespace, cfg: Any, client: Any) -> int:
    """§12.3's acceptance table, printed row by row. Non-zero on any failing row (§12.3, C10).

    Every expectation comes out of a checked-in `expected.json`; this command holds none of its
    own. A row that cannot run yet is a named `SKIP` and does not fail the command — but the count
    is in the summary and on the event stream, because a permanent skip nobody notices is the
    failure mode the unit's risk register names.
    """
    print(f"vsir eval acceptance — release {cfg.release_id}, §12.3, section {args.only}")
    report = acceptance.run(client, base=cfg.collection, dim=cfg.embed_dim,
                            release_id=cfg.release_id, only=args.only,
                            tc1e_fixture=args.tc1e_fixture or None)
    acceptance.print_report(report)
    _log.info("eval_acceptance", section=args.only, passed=report.passed, failed=report.failed,
              skipped=report.skipped, gains=len(report.gains), ok=report.ok)
    return EXIT_OK if report.ok else EXIT_REFUSED


def _cmd_eval_abstention(args: argparse.Namespace, cfg: Any, client: Any) -> int:
    """§12.4's adversarial eval. **A failure here is P0** — it is the injury, not a regression.

    `--corpus indexed` is §12.4's own wording: the sample is mutated from the observed-token
    inventory of *whatever corpus is indexed*, so after an ingest this is how the number gets
    measured on the real document. That path only reads.
    """
    print(f"vsir eval abstention — release {cfg.release_id}, §12.4, corpus {args.corpus}")
    report = abstention.run(client, base=cfg.collection, dim=cfg.embed_dim,
                            release_id=cfg.release_id, corpus=args.corpus,
                            collection=args.collection, doc_id=args.doc_id, sample=args.sample)
    abstention.print_report(report)
    log = _log.info if report.ok else _log.error
    log("eval_abstention", corpus=args.corpus, collection=report.collection,
        doc_id=report.doc_id, sample=report.sample, leaks=len(report.leaks),
        abstention_correctness=report.abstention_correctness,
        gate=abstention.CORRECTNESS_GATE, refusal=report.refusal, ok=report.ok)
    return EXIT_OK if report.ok else EXIT_REFUSED


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
        help="run the ingestion pipeline of §6.1 over one PDF; steps 01-11 at M2a",
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
        "--record", default="", metavar="DIR",
        help="freeze this run's VERBATIM S1/S2 bodies and the extractor's text into DIR, under "
             "the §6.3 keys replay reads them back by. This is how one paid ingest buys a "
             "permanent fixture (§12.1) — a flag on one run, never configuration, because "
             "nothing about which responses are in a fixture may be accidental",
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
    ingest_parser.add_argument(
        "--resume", default=None, metavar="RUN_ID",
        help="continue an existing run under its own id, taking its lease (D9). The id is kept "
             "because every point of the run carries it: a resume under a fresh id would write "
             "points publish's filter cannot find and retirement would delete as stale",
    )
    ingest_parser.add_argument(
        "--steal", action="store_true",
        help="take a lease that is still live. The lease is advisory — Qdrant has no "
             "compare-and-swap — so a duplicated worker re-bills windows but cannot corrupt the "
             "index: point_id is idempotent (I1) and nothing is queryable until the gates flip "
             "is_current (I7)",
    )
    ingest_parser.add_argument(
        "--override", action="append", default=[], metavar="GATE",
        help=f"publish past a held gate; §11.1 offers exactly {list(gates_module.OVERRIDABLE)}. "
             f"Needs --reason, which is recorded in the run and stamped on every page",
    )
    ingest_parser.add_argument(
        "--reason", default="",
        help="why the override is justified. Not defaulted: it is the only thing that will later "
             "explain why a document with a failing gate is in the index",
    )
    ingest_parser.set_defaults(handler=_cmd_ingest)

    runs_parser = commands.add_parser("runs", help="the run control plane of §6.9 (D9)")
    runs_commands = runs_parser.add_subparsers(dest="runs_command", metavar="<subcommand>",
                                               required=True)
    runs_show = runs_commands.add_parser(
        "show",
        help="print the run record of §6.9 — state, step, gate results, overrides, lease, cost "
             "and what retirement did; read from vsir_runs, so any process can answer",
    )
    runs_show.add_argument("run_id", help="the run id (a ULID, so id order is time order)")
    runs_show.set_defaults(handler=_with_store(_cmd_runs_show))

    gates_parser = commands.add_parser("gates", help="the publish gates of §11.1")
    gates_commands = gates_parser.add_subparsers(dest="gates_command", metavar="<subcommand>",
                                                 required=True)
    gates_rerun = gates_commands.add_parser(
        "rerun",
        help="re-evaluate the five gates against what is IN THE INDEX and record the result; "
             "free, and it publishes nothing",
    )
    gates_rerun.add_argument("run_id", help="the run to re-evaluate")
    gates_rerun.set_defaults(handler=_with_store(_cmd_gates_rerun))

    publish_parser = commands.add_parser(
        "publish",
        help="release a document a gate is holding (§4.4, §11.1): the reason is recorded in the "
             "run and every page is flagged published_with_override",
    )
    publish_parser.add_argument("run_id", help="the run to publish")
    publish_parser.add_argument(
        "--override", action="append", default=[], metavar="GATE",
        help=f"the gate to release; §11.1 offers exactly {list(gates_module.OVERRIDABLE)}",
    )
    publish_parser.add_argument("--reason", default="",
                                help="why the override is justified — required with --override")
    publish_parser.set_defaults(handler=_with_store(_cmd_publish))

    serve_parser = commands.add_parser(
        "serve",
        help="bind VSIR_PORT and serve the HTTP surface of §7.4 — the eight tools behind bearer "
             "auth, the run control plane, the two exports and the three free probes. The boot "
             "self-check runs first: a refusal exits non-zero with no socket bound (§4.3)",
    )
    serve_parser.add_argument(
        "--host", default=SERVE_HOST,
        help=f"the interface to bind (default: {SERVE_HOST}). The PORT is not a flag — it is "
             f"VSIR_PORT, because it is configuration and not a per-invocation choice (§15 III)",
    )
    serve_parser.set_defaults(handler=_cmd_serve)

    mcp_parser = commands.add_parser(
        "mcp",
        help="the MCP surface of §7.5 — the same tools, the same implementations, no second "
             "code path. --sse is the serving app (the SSE transport binds VSIR_PORT, §15 VII); "
             "--stdio is a one-off process speaking JSON-RPC on stdin/stdout",
    )
    transport = mcp_parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--stdio", action="store_true",
        help="speak MCP on stdin/stdout until the client closes the pipe (the default). stdout "
             "is the protocol, so events go to stderr and nothing else is printed",
    )
    transport.add_argument(
        "--sse", action="store_true",
        help=f"bind VSIR_PORT and serve GET {mcp_server.SSE_PATH} + POST "
             f"{mcp_server.MESSAGES_PATH} beside the HTTP tools — one process, one socket, both "
             f"protocols. Identical to `vsir serve`, which mounts them too",
    )
    mcp_parser.add_argument(
        "--host", default=SERVE_HOST,
        help=f"the interface --sse binds (default: {SERVE_HOST}); ignored by --stdio",
    )
    mcp_parser.set_defaults(handler=_cmd_mcp)

    lookup_parser = commands.add_parser(
        "lookup",
        help="JUMP (§7.2.2): the exact, phrase-only surface. One call through the release's own "
             "dispatcher, so this is the code path POST /tools/lookup runs. A typed absence "
             "exits 0 — searching and finding nothing is a successful call (§7.1)",
    )
    lookup_parser.add_argument("label", help="the code or label as printed, e.g. \"SF 1.1A\"")
    lookup_parser.add_argument(
        "--scope", action="append", default=[], metavar="KEY=VALUE",
        help="narrow the search, repeatable, e.g. --scope doc_id=SYN-M1 --scope page_no=5. A key "
             "outside INDEXED is a typed 400 (filter_unknown_key), never a slower answer",
    )
    lookup_parser.add_argument(
        "--include-unverified", action="store_true",
        help="also query the vlm_codes surface and return those separately, every one "
             "verified:false and never merged into hits (D3)",
    )
    lookup_parser.add_argument("--cap", type=int, default=LOOKUP_CAP,
                               help=f"how many hits of the set to return (default: {LOOKUP_CAP}). "
                                    f"It bounds the page of the set and nothing else — it cannot "
                                    f"move `weak` (§7.1)")
    lookup_parser.add_argument("--json", action="store_true",
                               help="print the envelope verbatim: the exact bytes an HTTP or MCP "
                                    "caller receives for the same request (§7.5)")
    lookup_parser.set_defaults(handler=_cmd_lookup)

    verify_parser = commands.add_parser(
        "verify",
        help="CHECK (§7.2.4): is each code actually printed on each page? Per (claim, page), "
             "three verdicts, and every claim absent is still a successful call",
    )
    verify_parser.add_argument("--claims", required=True, metavar="A,B,C",
                               help="comma-separated codes to check, e.g. \"K73,K158\"")
    verify_parser.add_argument("--pages", required=True, metavar="ID,ID",
                               help="comma-separated page ids, e.g. \"SYN-M1@1.0#p006\"")
    verify_parser.add_argument("--json", action="store_true",
                               help="print the envelope verbatim (see `lookup --json`)")
    verify_parser.set_defaults(handler=_cmd_verify)

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

    eval_parser = commands.add_parser(
        "eval",
        help="the evaluations of §12.3 and §12.4; `corpus` (§12.6) arrives at M8",
    )
    evals = eval_parser.add_subparsers(dest="eval", metavar="<eval>", required=True)
    acceptance_eval = evals.add_parser(
        "acceptance",
        help="the §12.3 acceptance table: one row per assertion, expected beside observed, "
             "non-zero on any failure",
    )
    acceptance_eval.add_argument(
        "--only",
        choices=[*acceptance.SECTIONS, "all"],
        default="all",
        help="which corpus to run: `synthetic` is the §13 M1 pages and always available, "
             "`parity` is the baseline impl already paid for, `real` is the pilot document "
             "(default: all)",
    )
    acceptance_eval.add_argument(
        "--tc1e-fixture",
        metavar="DIR",
        default="",
        help=f"where the pilot document's frozen fixture lives; overrides "
             f"${acceptance.TC1E_DIR_ENV} and the repository path",
    )
    acceptance_eval.set_defaults(handler=_with_store(_cmd_eval_acceptance))

    abstention_eval = evals.add_parser(
        "abstention",
        help="the §12.4 adversarial eval: 100 codes one character off real ones, none of which "
             "may answer. Reports abstention_correctness; a failure here is P0",
    )
    abstention_eval.add_argument(
        "--corpus",
        choices=list(abstention.CORPORA),
        default="synthetic",
        help="`synthetic` seeds the §13 M1 pages into a collection of its own and drops it; "
             "`indexed` reads the configured collection as it stands and writes nothing "
             "(default: synthetic)",
    )
    abstention_eval.add_argument(
        "--collection",
        metavar="NAME",
        default="",
        help="the collection --corpus indexed reads; defaults to $VSIR_COLLECTION_$VSIR_EMBED_DIM",
    )
    abstention_eval.add_argument(
        "--doc-id",
        dest="doc_id",
        metavar="DOC",
        default="",
        help="whose observed-token inventory the sample is mutated from; required when the "
             "collection holds more than one document",
    )
    abstention_eval.add_argument(
        "--sample",
        type=int,
        default=abstention.DEFAULT_SAMPLE,
        help=f"how many fabricated codes to generate (§12.4 asks for "
             f"{abstention.DEFAULT_SAMPLE})",
    )
    abstention_eval.set_defaults(handler=_with_store(_cmd_eval_abstention))

    return parser


def install_sigterm_handler() -> None:
    """Exit cleanly on ``SIGTERM`` (§15 Factor IX).

    The process-wide default: say so on the event stream, and exit 0 immediately. A command with
    work in flight replaces it for the duration — `vsir ingest` installs :func:`_install_drain`,
    which checkpoints the run as ``stopped`` first, so a kill loses at most the windows since the
    last checkpoint and never publishes a partial run (I7, F17). The server's own drain is
    uvicorn's, and it attaches in U014.
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
