# CR1 Implementation Progress

**Plan:** `development/cr1/plan/cr1-implementation-plan.md`
**Release tag:** (pending — set when all units are [x])

---

## Units

<!-- Claude updates this file after each unit. Format:
  - [ ] U001 Not started
  - [~] U002 In progress
  - [x] U003 Complete
  - [!] U004 Blocked — reason
  Record the demo command's output under "Demo evidence" when a unit completes. -->

### M0 — skeleton, pins, harness (spend: none)
- [ ] U001 Runtime skeleton, pins, and `vsir doctor`
- [ ] U002 Qdrant test harness, probes, and conformance greps

### M1 — `core/` and the exact surface on synthetic text (spend: none) — the whole proof
- [ ] U003 Page record, identifiers, and the `INDEXED` schema
- [ ] U004 Tokenisation, variants, the exact filter, and both envelopes
- [ ] U005 Synthetic exact surface, `lookup`, and `vsir demo exact`
- [ ] U006 `verify_claims`, `present_instead`, and the L3 abstention eval

### M2a — ingest a generated PDF with a stubbed VLM (spend: none)
- [ ] U007 Manifest, probe, render, S1 facts, and the windowing ladder
- [ ] U008 The VLM boundary, cache keys, replay mode, and S2 extraction
- [ ] U009 Derivation, health signals, label attribution, and stitching
- [ ] U010 Embedding, the three surfaces, the fingerprint, and indexing
- [ ] U011 Gates, publish, retirement, the run control plane, and exports

### M2b — ingest the pilot PDF; freeze the fixture (spend: S2 + embed, once)
- [ ] U012 Port the paid-for `impl` fixtures and the parity / negative sets — spend: none
- [ ] U013 The one paid `TC1E-SF` ingest and the `grounded_rate` baseline — spend: paid

### M3 — `lookup` + `verify` over HTTP and MCP (spend: none)
- [ ] U014 The serving app — auth, audit, budget, and degradation
- [ ] U015 `lookup` and `verify` over HTTP and MCP
- [ ] U016 `vsir eval acceptance` and `vsir eval abstention`

### M4 — `skim_pages`, `fetch`, `resolve` (spend: none)
- [ ] U017 `skim_pages`, deterministic fusion, image queries, and `resolve`
- [ ] U018 The page-image endpoint, the raster cache, and `fetch`

### M5 — the ladder rungs and `read` (spend: read)
- [ ] U019 `skim_documents`, `skim_sections`, and `searchable_ratio` — spend: none
- [ ] U020 `read` — the paid step, with stamped codes and a question-keyed cache — spend: paid

### M6 — the runner, the loop, the answer gate (spend: read)
- [ ] U021 Tri-state triage, the safeguards, and fetch-vs-read routing — spend: none
- [ ] U022 The loop, the six correction loops, the answer gate, and `POST /ask` — spend: paid

### M7 — operator console (spend: none, fixture-backed)
- [ ] U023 The operator console — viewer, agent panel, trust badges
- [ ] U024 The Playwright replay suite and `scripts/test-e2e.sh`

### M8 — revisions, resumable ingest, scale-out (spend: ingest)
- [ ] U025 Revisions, resumable ingest, and graceful shutdown — spend: none
- [ ] U026 `vsir eval corpus` — the §12.6 report and the D11 gates — spend: paid

---

## Milestone demos (Spec §0 — a milestone with no runnable demo is not complete)

| M | Demo command | Status | Evidence |
|---|---|---|---|
| M0 | `vsir doctor && bash scripts/test-unit.sh` | ⬜ | |
| M1 | `vsir demo exact --synthetic` | ⬜ | |
| M2a | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | ⬜ | |
| M2b | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | ⬜ | |
| M3 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | ⬜ | |
| M4 | `vsir demo narrow` | ⬜ | |
| M5 | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | ⬜ | |
| M6 | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | ⬜ | |
| M7 | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | ⬜ | |
| M8 | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ⬜ | |

---

## Notes

Record gaps, ambiguities and assumptions here as they are resolved.

### Open at planning time
- **OQ-1** pilot PDF location — blocks only U013's re-bill. Default: the operator places it at
  `data/source/TC1E-SF.pdf`; `data/source/` stays gitignored.
- **OQ-2** Gemini project/key — blocks the L4 halves of U013, U020, U022 and U026's real numbers.
  Default: replay mode (`VSIR_VLM=stub` + `VSIR_FIXTURE`), paid paths behind `VSIR_ALLOW_PAID=1`.
- **OQ-3 / OQ-7** Part A export hand-off (HTTP vs files on disk) — resolve before M8 (U011, U025).
- **OQ-5** one collection at 5,505-page scale — default one collection with `doc_id` scoping (U025).

### Stale spec text adjudicated during planning
See plan §8 SA-1…SA-12. The load-bearing ones: **SA-1** the dense vector **does** include the page
raster (C12/D4 win over §4.2's "Text only" row); **SA-2/SA-3** the sparse surfaces and RRF **ship**
(D2 wins over §2.2's out-of-scope row and §7.2.1's "there is no sparse vector" parenthetical);
**SA-4** the default answer route is `fetch`, not `read`.

### Spec changes made
None. Gap analysis found no true blocker — every apparent contradiction is resolved by Spec §2.3,
§3 or §17.
