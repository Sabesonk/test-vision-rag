"""The one refusal shape, and the OpenAPI response tables that publish it (§7.4, §11.3).

Every surface in this service refuses the same way — ``{"error": <code>, "detail": <prose>, ...}``
— and until this module existed **none of it was typed**. :class:`~vsir.serve.caps.ToolError`
built a dict in ``to_payload()``, the run routes had a hand-written ``ControlError``, and the
``responses=`` tables on every route carried a ``description`` and no ``model``. So the published
description said *"400: a typed bound of §7.3"* and told a generated client nothing about the
shape it would have to parse.

That is the gap this closes, and it is not cosmetic. §11.3's whole argument is that **an agent
switches on the code, not on the prose** — `fetch_budget_exceeded` and `dpi_requires_region` are
different next moves. A code that is real at runtime but absent from the schema is a contract the
caller has to learn from our source, and an enterprise client generating types off
``/openapi.json`` cannot switch on a field it was never told about.

**Why this is the one model in the service with ``extra="allow"``.** Every other model here
forbids extras, for the reason :class:`~vsir.serve.app.ToolRequest` gives: a silently-ignored
field is how a caller is told, with a straight face, that the corpus does not contain what they
misspelled. A refusal is the exact inverse. Its details *name the bound that was hit* — ``limit``
and ``requested`` on a cap, ``retryable`` on an outage, ``tool`` on every tool refusal, ``run_id``
on the control plane, ``available`` on an unknown tool name — and those keys differ per code.
Forbidding them would either drop the numbers the caller needs to make the next attempt correct,
or force this model to become the union of every bound's shape, which is a second source of truth
for the codes in `caps.py`. So the two named fields are the contract, and the details are
documented as open.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The refusal codes this service can emit, by the HTTP status they arrive under. Not an enum and
#: not validated against: `caps.py` and the tools own their codes, and a `Literal` here would be a
#: second declaration to drift. It is documentation — the list an integrator switches on — and it
#: is published in the schema's own description so it cannot be read without being seen.
CODES_BY_STATUS: dict[int, tuple[str, ...]] = {
    400: ("invalid_request", "invalid_json", "filter_unknown_key", "query_required",
          "read_empty", "read_page_cap_exceeded", "fetch_page_cap_exceeded",
          "fetch_budget_exceeded", "verify_pair_cap_exceeded", "skim_limit_exceeded",
          "dpi_not_allowed", "dpi_requires_region", "region_invalid"),
    401: ("unauthorized",),
    403: ("spend_not_permitted",),
    404: ("tool_not_found", "page_not_found", "run_not_found", "document_not_found"),
    413: ("upload_too_large",),
    415: ("not_a_pdf",),
    429: ("budget_exhausted",),
    500: ("internal_error",),
    502: ("vlm_error", "embed_error"),
    503: ("qdrant_unavailable", "vlm_unavailable", "store_unavailable"),
}


class ErrorResponse(BaseModel):
    """A typed refusal. ``error`` is the contract; ``detail`` is for the human reading the log.

    The details a code carries beside these two are open by design — see the module note. What is
    guaranteed is that both of these are always present and always strings, so a client can
    branch on ``error`` without a ``get`` and a ``None`` check.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "description": (
                "A refusal, never an empty result: an outage reported as 'nothing found' becomes "
                "a fabricated abstention (§7.1, §11.3). Switch on `error`. Additional properties "
                "name the bound that was hit — `limit`/`requested` on a cap, `retryable` on an "
                "outage, `tool` on a tool refusal, `available` on an unknown tool name."
            ),
            "examples": [
                {"error": "read_page_cap_exceeded",
                 "detail": "read takes at most 3 pages, got 7",
                 "tool": "read", "limit": 3, "requested": 7},
                {"error": "qdrant_unavailable",
                 "detail": "the index did not answer: ConnectionError. This is a refusal and not "
                           "an empty result",
                 "tool": "lookup", "retryable": True},
            ],
        },
    )

    error: str = Field(
        description="The machine-readable refusal code. An agent switches on this and never on "
                    "`detail` (§11.3).",
        examples=["dpi_requires_region"])
    detail: str = Field(
        description="Prose for the operator: what bound was hit and what was asked for, so the "
                    "next attempt can be correct rather than a retry of the same mistake.",
        examples=["dpi 400 renders a full page above the megapixel bound; pass a region"])


def responses(*statuses: int, **overrides: str) -> dict[int | str, dict[str, Any]]:
    """An OpenAPI ``responses=`` table for the given statuses, every one typed.

    Written as a helper rather than a constant per route because the *statuses* differ per route
    while the *model* never does: `read` can 429 and `lookup` cannot, the raster can 404 on a page
    id and the tool surface can 404 on a tool name. Passing the statuses keeps each route's
    declaration honest — it lists what it can actually return — while the schema stays one class.

    ``overrides`` replaces the default description for a status, for the routes where the same
    code means something more specific: ``responses(404, **{"404": "no such tool …"})``.
    """
    table: dict[int | str, dict[str, Any]] = {}
    for status in statuses:
        codes = CODES_BY_STATUS.get(status, ())
        described = overrides.get(str(status)) or _DESCRIPTIONS.get(status, "a typed refusal")
        if codes:
            described = f"{described} — `{'` · `'.join(codes)}`"
        table[status] = {"model": ErrorResponse, "description": described}
    return table


#: The default prose per status. One place, so two routes cannot describe the same status
#: differently and leave an integrator guessing which is right.
_DESCRIPTIONS: dict[int, str] = {
    400: "a typed bound of §7.3 — never a clamp and never a truncation",
    401: "no bearer token (§7.4); the probes and the description are the only free paths",
    403: "the release bills a live model and VSIR_ALLOW_PAID is not set",
    404: "named and absent — which is never the same as an empty result (§7.1)",
    413: "larger than the spool bound",
    415: "the bytes do not begin with %PDF-",
    429: "the per-caller `read` quota is exhausted (§7.3)",
    500: "a bug in this service, named by exception type and nothing more (§15.1)",
    502: "the model backend answered unusably",
    503: "a backing service did not answer — retryable, never empty (§11.3)",
}

#: The statuses every tool route can return. `read` adds 429 and the tool surface adds its own 404.
TOOL_STATUSES: tuple[int, ...] = (400, 401, 500, 502, 503)

__all__ = ["CODES_BY_STATUS", "ErrorResponse", "TOOL_STATUSES", "responses"]
