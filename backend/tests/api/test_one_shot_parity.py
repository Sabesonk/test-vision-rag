"""L2 — the `vsir <tool>` one-shots are the third surface of §7.5's one dispatcher (plan U015).

§7.5 and §4.4 between them make one claim about three surfaces: `POST /tools/{name}`, MCP (stdio
and SSE) and the `vsir lookup` / `vsir verify` one-shots all run *the same* implementation, so
there is no second code path and nothing to keep in step. `test_mcp_parity.py` proves two of the
three, byte for byte. This file proves the third.

It exists because the M3 milestone verification found the gap: `_one_shot` demonstrably calls
:func:`vsir.serve.app.dispatch` on reading, and nothing asserted it — while §4.4 calls the CLI
*"the only supported operational surface"*. A property that holds only on reading is a property
that stops holding the first time somebody adds a convenience to the CLI.

The check is the same one the MCP suite uses and for the same reason: **byte-identical**, not
equivalent JSON. `vsir lookup --json` prints `outcome.body()`, which is what makes
`vsir lookup … | jq` a reading of the wire contract rather than of a printed rendering — so a
re-serialisation anywhere in the CLI leg shows up here as a diff.

Run in this process rather than as a subprocess: the point is that `cli.main` reaches the shipped
dispatcher, and a subprocess would prove the same thing while hiding which callable answered.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vsir import cli
from vsir.eval import synthetic
from vsir.serve import app as app_module
from vsir.serve.app import create_app

from conftest import TEST_TOKEN, serve_env

EXPECTED = synthetic.load().expected
LABEL = EXPECTED["compact_labels"][0]["label"]
PAGE = EXPECTED["compact_labels"][0]["page_id"]
ABSENT = EXPECTED["suggest"]["label"]

CLI_SOURCE = Path(cli.__file__)


def http_body(name: str, arguments: dict) -> bytes:
    """The same call over `POST /tools/{name}`, as raw bytes. The thing the CLI must match.

    Built from `serve_env()` — the same dict the `one_shot` fixture puts in the environment — so
    the two sides differ in transport and in nothing else. `reads_remaining` is read from the
    budget ledger and is part of the body, so a mismatched `VSIR_READ_QUOTA` would show up as a
    byte diff that had nothing to do with the dispatcher.
    """
    with TestClient(create_app(serve_env())) as client:
        response = client.post(f"/tools/{name}", json=arguments,
                               headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        return response.content


@pytest.fixture
def one_shot(monkeypatch, capsys, served_collection):
    """`vsir <tool> … --json` in this process, returning `(exit code, printed bytes)`."""
    for name, value in serve_env().items():
        monkeypatch.setenv(name, value)

    def _run(*arguments: str) -> tuple[int, bytes]:
        code = cli.main([*arguments, "--json"])
        captured = capsys.readouterr()
        # The whole of stdout, not its last line: `--json` declares stdout the machine surface, so
        # a `boot_check_ok` in front of the body would fail every assertion below — which is the
        # point. The event stream is on stderr and is checked separately.
        return code, captured.out.rstrip("\n").encode("utf-8")

    return _run


# ── byte-identity, the criterion §7.5 states ────────────────────────────────────────────────────

@pytest.mark.parametrize("command,name,arguments", [
    pytest.param(["lookup", LABEL], "lookup",
                 {"label": LABEL, "scope": {}, "include_unverified": False, "cap": 20},
                 id="lookup-ok"),
    pytest.param(["lookup", ABSENT], "lookup",
                 {"label": ABSENT, "scope": {}, "include_unverified": False, "cap": 20},
                 id="lookup-not_found"),
    pytest.param(["lookup", EXPECTED["hallucinated"]["label"], "--include-unverified"], "lookup",
                 {"label": EXPECTED["hallucinated"]["label"], "scope": {},
                  "include_unverified": True, "cap": 20},
                 id="lookup-unverified"),
    pytest.param(["lookup", "3", "--scope", "page_no=5"], "lookup",
                 {"label": "3", "scope": {"page_no": 5}, "include_unverified": False, "cap": 20},
                 id="lookup-scoped"),
    pytest.param(["verify", "--claims", "K73", "--pages", "SYN-M1@1.0#p006"], "verify",
                 {"claims": ["K73"], "page_ids": ["SYN-M1@1.0#p006"]},
                 id="verify-absent"),
    pytest.param(["verify", "--claims", "SF 1.1A,K158", "--pages", f"{PAGE},SYN-M1@1.0#p008"],
                 "verify", {"claims": ["SF 1.1A", "K158"],
                            "page_ids": [PAGE, "SYN-M1@1.0#p008"]},
                 id="verify-two-claims"),
])
def test_the_one_shot_prints_the_bytes_an_http_caller_would_have_received(one_shot, command, name,
                                                                          arguments):
    """The criterion, as bytes. One serialiser, one dict, two transports (§7.5).

    The `arguments` beside each command are the request `_cmd_lookup` / `_cmd_verify` build, so
    a change to how the CLI maps its flags onto the tool's request model fails here rather than
    silently answering a different question than the flag implies.
    """
    code, printed = one_shot(*command)

    assert code == cli.EXIT_OK
    assert printed == http_body(name, arguments)


def test_a_typed_absence_is_exit_zero_from_a_one_shot(one_shot):
    """§7.1 — searching and correctly finding nothing is a successful call.

    It is also what lets §4.4's demo chain with `&&`, which is why it is asserted rather than
    assumed: a one-shot that exited non-zero on `not_found` would break the documented demo.
    """
    code, printed = one_shot("lookup", ABSENT)

    assert code == cli.EXIT_OK
    assert json.loads(printed)["status"] == "not_found"


def test_a_typed_refusal_is_the_same_body_and_a_non_zero_exit(one_shot):
    """I6 / F10 over the CLI: the `INDEXED` gate is under the dispatcher, not on a transport.

    The refusal's body is the HTTP body too — the same code, the same `keys` — because the check
    happens in one place. Only the exit code is the CLI's own contribution.
    """
    arguments = {"label": LABEL, "scope": {"content.text": "x"}, "include_unverified": False,
                 "cap": 20}

    code, printed = one_shot("lookup", LABEL, "--scope", "content.text=x")

    assert code == cli.EXIT_REFUSED
    assert printed == http_body("lookup", arguments)
    assert json.loads(printed)["error"] == "filter_unknown_key"


def test_an_unknown_scope_key_is_refused_before_it_reaches_the_index(one_shot):
    """The refusal names the key rather than returning a narrower answer that looks complete."""
    code, printed = one_shot("lookup", LABEL, "--scope", "bogus=1")

    assert code == cli.EXIT_REFUSED
    assert json.loads(printed)["keys"] == ["bogus"]


def test_a_cap_out_of_range_is_the_same_typed_400_the_http_surface_gives(one_shot):
    """§7.3 — a typed 400 naming its bound, never a clamp, on every surface (F18)."""
    arguments = {"label": LABEL, "scope": {}, "include_unverified": False, "cap": 0}

    code, printed = one_shot("lookup", LABEL, "--cap", "0")

    assert code == cli.EXIT_REFUSED
    assert printed == http_body("lookup", arguments)
    assert json.loads(printed)["error"] == "cap_out_of_range"


def test_with_json_the_event_stream_moves_to_stderr_and_is_not_silenced(monkeypatch, capsys,
                                                                          served_collection):
    """§15 Factor XI, applied the way `vsir mcp --stdio` applies it.

    `--json` declares stdout the machine surface, so the events go to stderr — **separated, never
    dropped**. Both halves are asserted, because silencing the boot self-check would be the worse
    bug of the two: an operator debugging a refusal needs every check it ran.
    """
    for name, value in serve_env().items():
        monkeypatch.setenv(name, value)

    cli.main(["lookup", LABEL, "--json"])

    captured = capsys.readouterr()
    body = json.loads(captured.out)                       # one document, and it parses
    assert body["status"] == "ok"
    events = [json.loads(line) for line in captured.err.splitlines() if line.strip()]
    assert events, "the event stream was silenced rather than moved"
    assert any(event["event"] == "boot_check_ok" for event in events)
    assert all("event" in event and "release_id" in event for event in events)


def test_without_json_stdout_is_still_the_event_stream(monkeypatch, capsys, served_collection):
    """The human rendering does not move anything: §15 Factor XI is the default, not the exception.

    Asserted so the stderr rule above stays scoped to the one flag that earns it. A command whose
    log destination depended on something less explicit than `--json` would be a command whose
    output a deployment could not predict.
    """
    for name, value in serve_env().items():
        monkeypatch.setenv(name, value)

    cli.main(["lookup", LABEL])

    captured = capsys.readouterr()
    assert any(line.startswith('{"') for line in captured.out.splitlines())
    assert "HIT" in captured.out
    assert captured.err == ""


# ── no second implementation (§7.5) ─────────────────────────────────────────────────────────────

def test_the_cli_reaches_the_same_callable_the_http_route_reaches(served_collection, monkeypatch):
    """Object identity, not resemblance: the tool table the CLI resolves **is** the release's.

    `runtime_from_env` builds a runtime for a process with no ASGI lifespan, and the assertion is
    that its table holds the same function objects `create_app` puts on `app.state.tools`. A CLI
    that had wrapped, re-capped or re-validated anything would fail this even if every byte above
    still matched.
    """
    for name, value in serve_env().items():
        monkeypatch.setenv(name, value)

    runtime, client = app_module.runtime_from_env(dict(serve_env()))
    try:
        with TestClient(create_app(serve_env())) as served:
            served_table = served.app.state.tools
    finally:
        client.close()

    assert set(runtime.tools) == set(served_table)
    for name, spec in runtime.tools.items():
        assert spec.call is served_table[name].call
        assert spec.request is served_table[name].request


def test_the_one_shots_have_no_tool_logic_of_their_own(one_shot):
    """`cli.py` calls `dispatch` and never a tool implementation directly.

    The import-graph half of the same claim, and the one that survives a refactor: `cli.py` may
    import `serve.tools.lookup` (it does, for the M1 demo's in-process assertions), so the
    assertion is about the **one-shot path** — `_one_shot` names `dispatch` and nothing else that
    could answer a query.
    """
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "_one_shot")

    called: set[str] = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                called.add(target.attr)
            elif isinstance(target, ast.Name):
                called.add(target.id)

    assert "dispatch" in called
    assert not {"lookup", "verify_claims", "exact_filter", "page_checks"} & called


def test_the_one_shot_identity_is_the_process_type_and_never_a_credential(one_shot, log_stream):
    """§15.1 — `local-cli` names the process, not the host and not the user.

    A `local-` line carries no personal identifier into a stream whose retention policy was
    written for digests, and it is a *stable* identity so the budget ledger has something to key
    on. Asserted here because the one-shots are the surface where an operator's own environment is
    closest to the code.
    """
    from vsir.serve import auth as auth_module

    identity = auth_module.local_identity(cli.CLI_PROCESS)

    assert identity.user_id == "local-cli"
    assert "@" not in identity.user_id and "/" not in identity.user_id
