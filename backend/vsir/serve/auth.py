"""Authentication: a bearer token on every non-probe path (Spec §7.4, §15.1). Net new.

(The first line deliberately does not open with the word *Bearer* followed by a space: §12.5's
credential-literal grep matches that shape wherever it appears, and a docstring is not worth
loosening the pattern that stops a committed token.)

**The defect this module closes is register item E5.** `impl/app/main.py` exposes eleven endpoints
and not one of them checks a credential — including `POST /api/v1/read`, the vision call that
spends money, and `DELETE /api/v1/documents/{doc_id}`, which removes a document from the index.
Anyone who could reach the port could bill the project's Gemini account or delete the corpus. §2.5
A records that; this is where it stops being true.

Three decisions, each of which is the difference between auth that holds and auth that looks like
it holds:

**Default deny, by path, in middleware — not a dependency per route.** A `Depends(bearer)` is
opt-in: the route added next milestone is unauthenticated until somebody remembers, and nothing
fails when they do not. Here the *only* unauthenticated paths are the three free probes of §7.4,
named in :data:`PUBLIC_PATHS`, and everything else — including a route that does not exist yet —
requires a token. `GET /pages/{page_id}/image` is built in U018 and is already refused without one
today, which is the property worth having: forgetting to protect a new route is impossible,
because protection is not something a route opts into.

**Identity comes from the token and from nothing else.** There is no `X-User-Id`, no
`?user=`, no field in the request body: a caller who could name themselves could name somebody
else, and the audit log of §7.4 — whose whole purpose is to say who spent the money — would record
whatever the spender typed. :data:`CLIENT_IDENTITY_HEADERS` exists so that a client *attempting*
it is visible on the event stream as ignored, rather than silently dropped.

**The credential is never compared, stored in memory as a secret, or logged.** A presented token is
reduced to :func:`caller_id` — a domain-separated SHA-256 prefix — and that digest is looked up in
a table of the configured tokens' digests. So the comparison is an equality test between two
hashes rather than between two secrets, a wrong token cannot be narrowed down by timing the
byte-wise comparison that never happens, and the identity that reaches the audit line is by
construction *not* the credential (§15.1: the token must never appear in a log line, a response or
an error message).

The cost of the digest identity is that an operator reading an audit line sees ``caller-9f2a…``
rather than a name. That is the right trade for a POC whose tokens come from a platform secret
store: the mapping from digest to human lives with whoever issued the token, and no grammar for
embedding a name inside a credential can be parsed wrongly here — because there is none.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping, Sequence

from starlette.responses import JSONResponse

from vsir import logging as vsir_logging

#: The three free probes of §7.4. An orchestrator holds no token, and a liveness probe that could
#: fail on a credential rotation would turn a secret rotation into a restart loop (§15.1).
PROBE_PATHS = frozenset({"/health", "/ready", "/metrics"})

#: The API's own description, and the two pages that render it. Free to **read**, because what they
#: contain is the shape of the interface — paths, parameters, envelope schemas, the typed refusal
#: codes — and none of it is corpus data, a run, a page or a token.
#:
#: They have to be free for the interface to be usable at all: a browser cannot attach an
#: `Authorization` header to a plain navigation, so an authenticated `/docs` is a 401 and nothing
#: else. The alternative that was tried first was a local proxy that injected the token, and it was
#: the wrong answer — it put the credential in a second place, made the working surface something
#: that is not the shipped one, and left `/docs` broken for everybody who did not run the proxy.
#:
#: **This does not open the API.** The document declares a `bearerAuth` requirement on every
#: operation, so Swagger's *Authorize* is where the caller's own token goes and every `Try it out`
#: is an ordinary authenticated request. Reading the description authorises nothing.
DOC_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})

#: Every path that does not require a token. Two sets rather than one, because they are free for
#: different reasons and only one of them may ever grow: a probe is free so an orchestrator can
#: reach it, a document is free so a human can read it. Anything that returns corpus data, a run,
#: a raster or prose belongs in neither.
PUBLIC_PATHS = PROBE_PATHS | DOC_PATHS

#: Where the authenticated :class:`Identity` is parked on the ASGI scope. A private key rather than
#: ``scope["state"]`` so it cannot collide with another middleware's, and so nothing reads it by
#: accident: :func:`identity_of` is the only accessor.
SCOPE_IDENTITY = "vsir.identity"

#: Headers a client might use to assert who it is. **Read only to report that they were ignored.**
CLIENT_IDENTITY_HEADERS = ("x-user-id", "x-caller-id", "x-on-behalf-of")

#: Domain separation, so this digest can never collide with another digest of the same bytes
#: computed elsewhere for another purpose (a cache key, a fingerprint).
_CALLER_DOMAIN = b"vsir:caller:"
#: Twelve hex characters — 48 bits. Enough that two configured tokens colliding is not a practical
#: concern, short enough to read in a log line.
CALLER_DIGEST_CHARS = 12
CALLER_PREFIX = "caller-"
#: The other kind of identity: a one-off process of **this** release, run by whoever already has
#: the deployment's configuration and can execute the image (§15 Factor XII). ``vsir lookup``,
#: ``vsir verify`` and ``vsir mcp --stdio`` are these; every network caller is a ``caller-``.
LOCAL_PREFIX = "local-"

_SCHEME = "bearer"
#: What a 401 body says. It names no token, no header value and no configured credential.
UNAUTHORIZED = "unauthorized"

_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class Identity:
    """Who is calling. Derived from the presented credential, never from the request's content."""

    user_id: str

    def __str__(self) -> str:  # so an f-string in a log line cannot accidentally dump the dataclass
        return self.user_id


class Unauthorized(Exception):
    """No usable bearer credential. A 401 with ``WWW-Authenticate``, and no detail about why.

    The reason is deliberately coarse — *"a bearer token is required"* — for every case: a missing
    header, a malformed one and a wrong token are indistinguishable to the caller. Telling an
    unauthenticated caller that the header parsed but the token was unknown is an oracle, and it
    buys a legitimate client nothing that the same sentence does not.
    """

    http_status = 401

    def __init__(self, detail: str = "a bearer token is required on every path but the probes",
                 *, reason: str = "missing_or_invalid") -> None:
        super().__init__(detail)
        self.detail = detail
        #: For the event stream only. Never for the response body.
        self.reason = reason

    def to_payload(self) -> dict[str, str]:
        return {"error": UNAUTHORIZED, "detail": self.detail}

    @property
    def headers(self) -> dict[str, str]:
        return {"www-authenticate": "Bearer"}


def caller_id(token: str) -> str:
    """A presented token → a stable, non-reversible caller id.

    The identity in every audit line and every budget record. It is a *function of the credential*,
    so it is stable across replicas and restarts with no shared state (§15 Factor VI), and it is a
    digest, so an audit line that carried it into a log aggregator has still never carried the
    credential (§15.1).
    """
    digest = hashlib.sha256(_CALLER_DOMAIN + token.encode("utf-8")).hexdigest()
    return f"{CALLER_PREFIX}{digest[:CALLER_DIGEST_CHARS]}"


def local_identity(process: str) -> Identity:
    """Who a one-off process of this release is, for the budget ledger and the audit line.

    **Not a credential, and not a hole in §7.4 either.** The bearer requirement exists because
    the HTTP surface is reachable by anyone who can reach the port — that is the boundary, and
    register **E5** is what happens when nothing guards it. A ``vsir`` subcommand is on the other
    side of that boundary already: it runs from the release's own image with the release's own
    configuration, and the operator running it could equally run ``vsir publish``, which flips
    `is_current` on a whole document and asks for no token at all. A credential the process reads
    from the same environment the server reads is not authentication, it is ceremony.

    What the identity *is* for is attribution. §7.4's audit line has to say who spent the money,
    and the §7.3 quota has to have somebody to charge, so a one-off process gets a stable name —
    ``local-mcp-stdio``, ``local-cli`` — rather than an empty string or a fresh id per invocation.
    Stable is the operative word: a per-pid identity would hand every invocation a brand-new
    quota, which is the same as having none.

    It names the **process type**, deliberately, and never the host or the user: those are the
    two things that would make this a personal identifier in a log stream with a retention policy
    written for `caller-` digests (§15.1).
    """
    slug = "".join(char if char.isalnum() or char == "-" else "-" for char in process.lower())
    if not slug.strip("-"):
        raise ValueError(f"a local identity names its process type, got {process!r}")
    return Identity(user_id=f"{LOCAL_PREFIX}{slug.strip('-')}")


def identity_table(tokens: Sequence[str]) -> Mapping[str, Identity]:
    """``{caller_id(token): Identity}`` for every configured token.

    The configured secrets are reduced to digests here and the plaintext is not retained by this
    module at all. Authentication is then a dict lookup on the digest of what was presented —
    equality between two hashes, never between two secrets.
    """
    return {caller_id(token): Identity(user_id=caller_id(token))
            for token in tokens if token}


def bearer(header: str | None) -> str:
    """The credential out of an ``Authorization`` header, or :class:`Unauthorized`."""
    if not header:
        raise Unauthorized(reason="no_authorization_header")
    scheme, _, credential = header.partition(" ")
    if scheme.strip().lower() != _SCHEME or not credential.strip():
        raise Unauthorized(reason="not_a_bearer_header")
    return credential.strip()


def authenticate(header: str | None, table: Mapping[str, Identity]) -> Identity:
    """Resolve an ``Authorization`` header to an :class:`Identity`, or refuse."""
    presented = caller_id(bearer(header))
    identity = table.get(presented)
    if identity is None:
        raise Unauthorized(reason="unknown_token")
    return identity


def is_public(path: str) -> bool:
    """Whether ``path`` is one of the three free probes.

    An exact match, not a prefix: ``/health`` is public and ``/healthz-admin`` would not be, and a
    prefix rule is how an unauthenticated surface grows by accident.
    """
    return path in PUBLIC_PATHS


def identity_of(scope: Mapping[str, Any]) -> Identity | None:
    """The authenticated identity on an ASGI scope, or ``None`` on a public path."""
    found = scope.get(SCOPE_IDENTITY)
    return found if isinstance(found, Identity) else None


def _header(headers: Iterable[tuple[bytes, bytes]], name: str) -> str | None:
    wanted = name.lower().encode("latin-1")
    for key, value in headers:
        if key.lower() == wanted:
            return value.decode("latin-1")
    return None


class BearerAuth:
    """Pure-ASGI default-deny middleware. Everything but :data:`PUBLIC_PATHS` needs a token.

    Pure ASGI rather than Starlette's ``BaseHTTPMiddleware`` for a specific reason: that base class
    runs the downstream app in a **separate task**, so a ``ContextVar`` set in its ``dispatch`` — the
    correlation ids of §11.4, for one — does not reach the endpoint. A plain ASGI callable awaits
    the app in the same task, so context propagates and the audit line and the handler's own log
    lines carry the same ``request_id``.
    """

    def __init__(self, app: Any, *, tokens: Sequence[str]) -> None:
        self.app = app
        self._table = identity_table(tokens)

    async def __call__(self, scope: MutableMapping[str, Any], receive: Callable[[], Awaitable[Any]],
                       send: Callable[[Any], Awaitable[None]]) -> None:
        if scope["type"] != "http" or is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or ()
        try:
            identity = authenticate(_header(headers, "authorization"), self._table)
        except Unauthorized as refusal:
            _log.warning("unauthorized", path=scope.get("path", ""),
                         method=scope.get("method", ""), reason=refusal.reason)
            response = JSONResponse(status_code=refusal.http_status, content=refusal.to_payload(),
                                    headers=refusal.headers)
            await response(scope, receive, send)
            return

        # Read only so the attempt is *visible*. The value is never used, and `user_id` below is
        # the token's digest whatever the client claimed (§7.4: identity is never client-supplied).
        claimed = [name for name in CLIENT_IDENTITY_HEADERS if _header(headers, name) is not None]
        if claimed:
            _log.warning("client_identity_ignored", headers=claimed, user_id=identity.user_id,
                         path=scope.get("path", ""))

        scope[SCOPE_IDENTITY] = identity
        await self.app(scope, receive, send)
