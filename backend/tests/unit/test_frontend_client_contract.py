"""L0 — the console's typed client against the models it claims to mirror (U023).

U023's risk register names this exactly: the console is *"the first real consumer of
``inline=false``, ``thumb_url`` and the badge fields, built four milestones after those envelopes
were frozen — contract mismatches surface only here"*, and the mitigation it asks for is to
*"generate the frontend's typed client from ``serve/envelope.py`` and pin it by
``schema_version``, so a mismatch is a compile error rather than a runtime surprise"*.

**This is that mitigation, with one deliberate substitution.** No code generator runs: a generated
client would be a build step that has to be re-run, checked in, and noticed when it was not. What
runs instead is this test, and it is strictly stronger in the direction that matters. A generator
copies the service's shape into the client, so it can only catch a field the service *added*. This
compares the two shapes and fails on either side — including the case a generator is blind to, a
field the console believes in that the service has never sent, which is how a panel renders
``undefined`` in production and nobody finds out until an operator reads it.

The comparison is a **field-name** one, not a type one. That is the honest limit of reading
TypeScript with a regular expression, and it is where the value is anyway: `tsc --noEmit` already
holds the frontend to its own declarations, and the failure mode this guards is a rename or an
addition on the Python side, not a `str` that became an `int`.

Three things beyond the field sets are pinned here because each is a **string a person reads**
rather than a shape a compiler checks: ``SCHEMA_VERSION``, the two badge labels, and the amber
warning. §13 M7 calls the badges load-bearing UI, and `answer.BADGE_READ_FROM_IMAGE` says in its
own docstring that rewording it is a change to a product contract — so a paraphrase in the browser
is that change, made silently and in the one place nobody greps.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from vsir.core import record, status
from vsir.runner import answer as answer_module
from vsir.runner import loop as loop_module
from vsir.serve import app as app_module
from vsir.serve import envelope, inputs, manage

REPO = Path(__file__).resolve().parents[3]
TYPES_TS = REPO / "frontend" / "src" / "api" / "types.ts"
REQUESTS_TS = REPO / "frontend" / "src" / "api" / "requests.ts"

#: Every response interface in `types.ts`, and the model it says it is.
RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "Provenance": envelope.Provenance,
    "ImageRef": envelope.ImageRef,
    "Preview": envelope.Preview,
    "NextMoves": envelope.NextMoves,
    "DocScopeStat": envelope.DocScopeStat,
    "ScopeStats": envelope.ScopeStats,
    "DocHit": envelope.DocHit,
    "SectionHit": envelope.SectionHit,
    "PageHit": envelope.PageHit,
    "LookupHit": envelope.LookupHit,
    "ResolveHit": envelope.ResolveHit,
    "SearchResponse": envelope.SearchResponse,
    "ClaimVerdict": envelope.ClaimVerdict,
    "VerifyResult": envelope.VerifyResult,
    "FetchImage": envelope.FetchImage,
    "FetchPage": envelope.FetchPage,
    "FetchResult": envelope.FetchResult,
    "Summary": record.Summary,
    "ReadCode": envelope.ReadCode,
    "PageProvenance": envelope.PageProvenance,
    "ReadResult": envelope.ReadResult,
    "ToolEnvelope": envelope.ToolEnvelope,
    "RenderedClaim": answer_module.RenderedClaim,
    "Check": answer_module.Check,
    "Answer": answer_module.Answer,
    "Abstention": answer_module.Abstention,
    "Move": loop_module.Move,
    "TriageRow": loop_module.TriageRow,
    "TriageTable": loop_module.TriageTable,
    "AskResponse": app_module.AskResponse,
    # U031's corpus rows. They were declared in `client.ts` instead of here, where this test does
    # not look, and every field of them was wrong — which is the argument for the ledger being
    # exhaustive rather than for it being long.
    "RevisionRow": manage.RevisionRow,
    "DocumentRow": manage.DocumentRow,
    "DocumentList": manage.DocumentList,
}

#: The request bodies. Checked as a **subset**: `ToolRequest` forbids extras, so a field the
#: console sends that the model does not declare is a `400` in production — but a field the model
#: declares and the console never sends is simply one it does not use (`AskRequest.draft` is the
#: standing example; the console asks questions and does not submit drafts to the gate).
REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "LookupBody": inputs.LookupRequest,
    "VerifyBody": inputs.VerifyRequest,
    "SkimPagesBody": inputs.SkimPagesRequest,
    "SkimAggregateBody": inputs.SkimDocumentsRequest,
    "ResolveBody": inputs.ResolveRequest,
    "FetchBody": inputs.FetchRequest,
    "ReadBody": inputs.ReadRequest,
    "AskBody": app_module.AskRequest,
}

_INTERFACE = re.compile(r"^export interface (\w+)(?:<[^>]*>)?\s*\{$", re.MULTILINE)
_FIELD = re.compile(r"^  (\w+)\??:", re.MULTILINE)


def _interfaces(source: str) -> dict[str, set[str]]:
    """Every `export interface` in a TypeScript module → its top-level field names.

    Fields are matched at exactly two spaces of indentation, which is what makes this safe without
    a parser: a nested object literal would be indented further and an index signature
    (``[key: string]: unknown``) does not start with a word character. Both appear in `types.ts`
    already, so the narrowness is load-bearing rather than incidental.
    """
    found: dict[str, set[str]] = {}
    matches = list(_INTERFACE.finditer(source))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[start:end].split("\n}")[0]
        found[match.group(1)] = set(_FIELD.findall(body))
    return found


@pytest.fixture(scope="module")
def declared() -> dict[str, set[str]]:
    return _interfaces(TYPES_TS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def requested() -> dict[str, set[str]]:
    return _interfaces(REQUESTS_TS.read_text(encoding="utf-8"))


def test_the_parser_actually_read_the_file(declared: dict[str, set[str]]) -> None:
    """A contract test that parsed nothing would pass silently, which is the worst outcome here."""
    assert len(declared) >= len(RESPONSE_MODELS)
    assert declared["ImageRef"] == {"url", "thumb_url", "dpi", "width", "height"}


@pytest.mark.parametrize("name", sorted(RESPONSE_MODELS))
def test_response_interface_matches_its_model(name: str, declared: dict[str, set[str]]) -> None:
    """Field for field, in both directions — see the module docstring on why both."""
    model = RESPONSE_MODELS[name]
    assert name in declared, f"{name} is in the ledger above but not in types.ts"
    ours = set(model.model_fields)
    theirs = declared[name]
    assert theirs == ours, (
        f"{name} has drifted.\n"
        f"  the service sends, the console does not read: {sorted(ours - theirs)}\n"
        f"  the console reads, the service does not send: {sorted(theirs - ours)}"
    )


@pytest.mark.parametrize("name", sorted(REQUEST_MODELS))
def test_request_body_is_a_subset_of_what_the_tool_accepts(
    name: str, requested: dict[str, set[str]],
) -> None:
    """Every parameter the console sends must exist, because `extra="forbid"` makes it a 400."""
    model = REQUEST_MODELS[name]
    assert name in requested, f"{name} is in the ledger above but not in requests.ts"
    unknown = requested[name] - set(model.model_fields)
    assert not unknown, (
        f"{name} sends parameter(s) {sorted(unknown)} that {model.__name__} forbids — "
        f"every one of those is an `invalid_request` 400 at runtime"
    )


def test_schema_version_is_pinned(declared: dict[str, set[str]]) -> None:
    """The console asserts this against `provenance`, so it has to be the same number."""
    assert declared  # the module parsed
    source = TYPES_TS.read_text(encoding="utf-8")
    match = re.search(r"export const SCHEMA_VERSION = (\d+)", source)
    assert match is not None, "types.ts no longer pins SCHEMA_VERSION"
    assert int(match.group(1)) == record.SCHEMA_VERSION


def _const(source: str, name: str) -> str:
    """A `export const NAME = '…'` or a `'…' + '…'` continuation, as one string."""
    match = re.search(rf"export const {name} =\s*(.+?)\n\n", source, re.DOTALL)
    assert match is not None, f"types.ts no longer declares {name}"
    return "".join(re.findall(r"'([^']*)'", match.group(1)))


def test_the_badge_wording_is_the_services_own() -> None:
    """§13 M7 calls these load-bearing; `answer.py` calls a reword a product-contract change."""
    source = TYPES_TS.read_text(encoding="utf-8")
    assert _const(source, "BADGE_VERIFIED") == answer_module.BADGE_VERIFIED
    assert _const(source, "BADGE_READ_FROM_IMAGE") == answer_module.BADGE_READ_FROM_IMAGE
    assert _const(source, "WARNING_UNVERIFIABLE") == answer_module.WARNING_UNVERIFIABLE


def test_the_six_value_status_enum_is_complete() -> None:
    """Six values, four of them absences — and the console draws a different badge for each."""
    source = TYPES_TS.read_text(encoding="utf-8")
    union = re.search(r"export type Status =\n(.+?)\n\n", source, re.DOTALL)
    assert union is not None
    assert set(re.findall(r"'(\w+)'", union.group(1))) == {member.value for member in status.Status}

    absences = re.search(r"export const ABSENCES: readonly Status\[\] = \[(.+?)\]", source, re.DOTALL)
    assert absences is not None
    assert set(re.findall(r"'(\w+)'", absences.group(1))) == {item.value for item in status.ABSENCES}


def test_the_check_vocabulary_is_the_three_states() -> None:
    """One vocabulary for checks (I6) — `verified` stays a boolean and is not in this union."""
    source = TYPES_TS.read_text(encoding="utf-8")
    union = re.search(r"export type CheckState = (.+)", source)
    assert union is not None
    assert set(re.findall(r"'(\w+)'", union.group(1))) == set(status.CHECK_STATES)


def test_the_text_trust_levels_match_and_unsearchable_excludes_degraded() -> None:
    """`degraded` is a text layer with problems, not one that cannot be read (§5.7)."""
    source = TYPES_TS.read_text(encoding="utf-8")
    trust = re.search(r"export type TextTrust = (.+)", source)
    assert trust is not None
    assert set(re.findall(r"'(\w+)'", trust.group(1))) == set(record.TextTrust.__args__)

    unsearchable = re.search(r"export const UNSEARCHABLE_TRUST: readonly TextTrust\[\] = \[(.+?)\]",
                             source, re.DOTALL)
    assert unsearchable is not None
    assert set(re.findall(r"'(\w+)'", unsearchable.group(1))) == set(record.UNSEARCHABLE_TRUST)


def test_no_score_field_reaches_the_browser() -> None:
    """§7.6's refusal, on the client side of the wire.

    A **field declaration**, not the word: Spec §12.5's greps are about a field named `score` in a
    response model, and `types.ts` says in prose that there is no score anywhere in this surface.
    A check that could not tell those apart would forbid the file from documenting the rule it
    enforces.
    """
    source = TYPES_TS.read_text(encoding="utf-8")
    assert re.search(r"^\s*score\??:", source, re.MULTILINE) is None
