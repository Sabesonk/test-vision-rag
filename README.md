# vsir — Vision Segmentation, Index & Retrieval (POC Part B)

Ask an engineering question of a 1,440-page machine manual and get either a page-cited answer or an
honest refusal. Never a plausible wrong one.

The guarantee is negative and it is the whole product: **a code this service returns is a code
printed on the page.** Everything below exists to make a wrong answer structurally impossible
rather than statistically unlikely — one exact-match path, four typed absences instead of an empty
`200`, a verification stamp on every claim, and an assertion behind every rule.

- **Spec (authoritative):** [development/cr1/spec/spec.md](development/cr1/spec/spec.md)
- **Plan:** [development/cr1/plan/cr1-implementation-plan.md](development/cr1/plan/cr1-implementation-plan.md)
- **Progress:** [development/cr1/progress/implementation-progress.md](development/cr1/progress/implementation-progress.md)
- **Commands:** [AGENTS.md](AGENTS.md)

## The one rule

`ingest/probe.py` is the only writer of the `text` payload field. Model output never reaches a
lexical index except through `vlm_codes`, which is opt-in and permanently `verified: false`. That is
what makes "the code was printed on the page" a property of the schema rather than a hope about the
model.

## Closed decisions

These were left open by `plan2` and are closed by the spec (§3). Three of them were re-decided
against the previous working implementation once it came to light — evidence beats inference.

| # | Decision | Ruling |
|---|---|---|
| **D1** | Is the graph team still a consumer of the ingest export? | **Yes.** The export stays; its shape changes to page-level `labels.jsonl` carrying `page_range`, `sections[]`, `summary`, `codes_in_text[]` and `safety_flag` (§6.8). It is a contract with Part A, not an internal artefact. |
| **D2** | Does the sparse / lexical vector earn its place? | **Yes — ported, and the third surface finally populated.** Three fused surfaces (`page` 1.0, `lexical` 1.0, `captions` 0.4) combined by RRF at `rrf_k=60`. `captions` was declared and weighted but never written in the previous implementation; it is now written from the S2 `summaries[]` + `topics`. RRF is **ranks only** — no similarity value is ever computed, stored or returned. |
| **D3** | Does `vlm_codes` ship? | **Yes, opt-in, and always `verified: false`.** It is the only recall on scanned pages and zero-text vendor files, and correction Loop 5 depends on it. Disclosed and separable, never blended into `text`. |
| **D4** | How is the dense vector composed? | **One page → one fused `gemini-embedding-2` vector**, image and text interleaved as separate `types.Part`s in a single `types.Content`, raster last. Three API constraints are load-bearing: `task_type` is rejected by this model; a bare list in `contents` returns one aggregated embedding, so each page is wrapped in its own `Content` and the returned count is verified with a per-item fallback; `output_dimensionality` is MRL truncation, and the dim is recorded in the collection name and the fingerprint. |
| **D5** | Per-language summaries? | **`lang[]` per page, one summary per dominant language** under `content.summaries[]`. One blended IT/EN summary poisons the embedding. |
| **D6** | Bounding boxes, `around="K158"`? | **Deferred.** `region=[x0,y0,x1,y1]` normalised only — no storage exists for boxes, and `region` already delivers the zoom. |
| **D7** | Is the MCP surface or the runner the supported entry point? | **Both ship; only the runner may compose an answer.** Every rule that matters is enforced server-side — the typed envelopes, publish gating, the caps and the answer gate — because an MCP client brings its own prompt and prompt-level rules are advisory. |

The remaining five (§3): **D8** no multivector — superseded by D4; **D9** run and window state live in
the `vsir_runs` Qdrant collection under an advisory lease, never on local disk; **D10** deterministic
replay (`VSIR_VLM=stub` + `VSIR_FIXTURE`) is how CI runs the whole loop with no API key; **D11** the
corpus gates — `code_precision` and `abstention_correctness` must be **1.00**; **D12** image queries
and image *references* (never bytes) on every hit.

## Layout

```text
backend/vsir/      the service and the CLI — core/ ingest/ vlm/ serve/ mcp/ runner/
backend/tests/     unit/ (L0-L1)  api/ (L2-L3)  paid/ (L4)
frontend/          React + TypeScript + Vite — M7 only
data/fixtures/     frozen extractions, checked in — replayed forever, never re-billed
development/cr1/   spec, plan, progress
```

Modules are created by the milestone that implements them, never as empty placeholders: Spec §4.1
is a map, not a checklist.

## Running it

Configuration is the environment and only the environment. Copy the example, fill it in, load it:

```bash
cp .env.example .env && set -a && . ./.env && set +a
vsir doctor
```

`vsir doctor` is the boot self-check of §4.3. It prints `release_id`, the resolved model ids and the
index fingerprint, and it **refuses to start** — non-zero, with a named reason — on a model id
ending `-latest`, a missing required variable, a live payload schema that has drifted from
`INDEXED`, a collection fingerprint that does not match the configured embedding model, or a `text`
index without `phrase_matching`. It never degrades to a partial service.

The image carries no configuration and no secret. Tag it with the release id, never `latest`, and
run it read-only:

```bash
docker build -t vsir:$VSIR_RELEASE_ID -f backend/Dockerfile backend
docker run --read-only --tmpfs /tmp:rw,noexec,nosuid,size=512m --env-file .env vsir:$VSIR_RELEASE_ID doctor
```

## What binds every change

- **Config from the environment.** A deployment-varying value is an env var in `.env.example`. Model
  ids and prompt versions feed cache keys and the collection fingerprint, so changing one is a
  release, not a hot edit.
- **Stateless processes.** No session state, nothing correctness-bearing in process memory or on
  local disk. Rasters are re-rendered on demand into an in-process cache and are never a source of
  truth.
- **Logs are an event stream.** Structured JSON to stdout, one event per line, carrying
  `release_id`, `run_id`, `session_id`, `request_id` and `tool`. The app never opens a log file.
- **Dev/prod parity.** The stub VLM is selected by `VSIR_VLM=stub`, never by a code branch and
  never by a test-only import. There is no `if TESTING:` in the production path.
- **One image, many process types.** `web`, `ingest-worker` and one-off `vsir` admin commands all
  run from the same image and release. An operational action that cannot be a `vsir` subcommand is
  not a supported operation.
