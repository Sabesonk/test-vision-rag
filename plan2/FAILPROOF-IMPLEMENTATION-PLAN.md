# The fail-proof implementation plan

> **What "fail-proof" can mean here, and what it cannot.**
>
> This system will sometimes fail to find a page, and a vision model reading a scanned
> raster will sometimes misread a character. No plan removes those. What a fail-proof
> implementation guarantees is narrower and achievable:
>
> ### No failure may present itself as a correct answer.
>
> In a corpus where 8,414 code pairs differ by one character, the only unrecoverable
> failure is a **confident wrong answer** — sending a technician to rewire `K78` when the
> page says `K73`. Everything below exists to make every other failure *visible, typed and
> attributable* instead.

This document is the engineering half of the plan. It assumes the spec fixes in the review
(S01–S26, N1–N6) and adds what those findings do not cover: the invariants that must be
enforced in code rather than by convention, the catalogue of paths to a wrong answer, the
tests that hold each closed, and the order of work that proves the design before it spends
money.

---

## 1 · Eight invariants, each enforced by an assertion

A design rule that lives only in prose decays on the third sprint. Each rule below has a
mechanical enforcement, and each enforcement has a test that fails if someone removes it.

### I1 · One page, one point

```python
point_id = uuid5(NAMESPACE, page_id)             # idempotent: re-ingest overwrites
assert len({r.page_id for r in records}) == len(records)
assert count(doc_id=d, revision=r) == pdf.page_count      # after publish
```

A page is never subdivided and never duplicated. This is what makes *"cite page 54"*
possible; without the post-publish count, a partially-failed run leaves a document that
looks complete.

### I2 · The exact surface contains only extracted text

The one rule of the whole design, made mechanical:

```python
# ingest/probe.py is the ONLY writer of the `text` field
def test_only_probe_writes_text():
    for path in source_files("ingest/", "serve/"):
        if path.name != "probe.py":
            assert '"text":' not in read(path) and "text=" not in writes_to_payload(path)

def test_hallucinated_code_is_unfindable():
    index(page(text="B221 K158 SI3", codes=["K999"]))       # model claims K999
    assert lookup("K999").status == "not_found"              # exact surface: nothing
    assert lookup("K999", include_unverified=True).unverified_hits   # labelled, separate
```

The second test is the design's thesis as an executable statement. If it ever passes with a
hit in `hits` rather than `unverified_hits`, the "verified by construction" property is
gone.

### I3 · Exact matching is phrase-only, and varies only by whitespace

```python
def exact_filter(label, scope):                  # the ONLY exact-match code path
    return Filter(should=[
        Filter(must=[FieldCondition(key="text", match=MatchPhrase(phrase=v)), *scope])
        for v in variants(label)])

def test_no_any_order_matching_anywhere_in_serve():
    src = read_all("serve/")
    assert "MatchText" not in src and "MatchTextAny" not in src

def test_variants_differ_only_in_whitespace():
    """The mechanical proof that this is not fuzzy matching."""
    for label in ["SF 1.1A", "K73", "EAO 84-5140.0020", "S202-S203", "SF121.1A"]:
        base = re.sub(r"\s+", "", label).lower()
        for v in variants(label):
            assert re.sub(r"\s+", "", v).lower() == base      # K73 can never yield K78
```

`variants()` emits three spellings of the *same characters* — as given, whitespace removed,
and a space at every letter↔digit boundary. The property test is what separates this from
edit distance: no variant can ever change a character, so the fourth refusal holds by
construction rather than by review.

### I4 · The page offset is proved, never assumed

The single most dangerous line in the pipeline, because a wrong value shifts every page,
citation and summary and **nothing errors**:

```python
abs_page = window.start + page_index - 1

# 1. structural: the window returned exactly the pages it was given
assert sorted(p.page_index for p in out.pages) == list(range(1, window.pages + 1))

# 2. independent: the printed label the model read must be in THIS page's text
if has_text[i] and out.printed_page_no:
    if not phrase_in(tok(out.printed_page_no), tok(text[i])):
        if phrase_in(tok(out.printed_page_no), tok(text[i-1])) or \
           phrase_in(tok(out.printed_page_no), tok(text[i+1])):
            raise OffsetError(window)        # the off-by-one signature — reject, re-bill
```

Check 2 is the one that matters: it is an *independent* observation of the same fact, so an
offset bug cannot pass both. On failure the window is rejected and bisected — never padded,
never offset-guessed.

### I5 · Absence is typed; an empty list is never a bare `200`

```python
class ToolResponse(BaseModel):
    status: Literal["ok", "not_found", "not_searchable",
                    "out_of_scope", "found_only_in_superseded", "error"]
    hits: list[Hit] = []
    scope_stats: ScopeStats               # pages, pages_no_text, docs[{doc_id, ratio}]

    @model_validator(mode="after")
    def empty_is_never_ok(self):
        assert self.hits or self.status != "ok"
        return self
```

The validator is the enforcement: a tool physically cannot return an empty `ok`. Backend
failure is a 5xx, because a failed call returned as an empty call turns our outage into the
agent's fabricated abstention.

**Why five states and not four.** The fifth exists because I7 creates a new way to be
confidently wrong. Once `is_current` is injected by default, a label that appears only in
revision 1.3 after 1.4 is published returns *nothing* — and `not_found` on it means *"this
code does not exist"* about a code that is printed in the binder on the shelf. So a miss that
would have hit with `include_superseded=True` returns `found_only_in_superseded` with the
revision and page_ids, and the agent decides. Every guard that hides data must own the
absence it creates.

### I6 · Nothing is filtered on an unindexed field

```python
INDEXED = {"doc_id": "keyword", ..., "has_text": "bool", "page_no": "integer"}   # one dict

for field, kind in INDEXED.items():                    # creates the indexes
    client.create_payload_index(collection, field, SCHEMA[kind])

def scope_conditions(scope):                           # and gates the filters
    unknown = set(scope) - set(INDEXED)
    if unknown: raise FilterError(unknown)             # 400, never a silent scan

def on_startup():                                      # and asserts they still exist
    live = client.get_collection(collection).payload_schema
    if set(INDEXED) - set(live): refuse_to_serve()
```

One dict creates the indexes, gates the filters, and is asserted against the live
collection at boot. The three cannot drift.

### I7 · A run that has not passed its gates cannot answer

The failure this closes is subtle and it is an *abstention* failure, which makes it easy to
miss: a 1,440-page manual is hundreds of windows, and a crash at window 700 leaves 700 pages
indexed. If those pages are queryable, `skim_documents` reports a plausible
`searchable_ratio`, the ladder finds nothing on the missing pages, and the loop routes that to
*"not in these documents"* — about a page that is in the document.

```python
# step 09 writes every point unpublished
payload["is_current"] = False

# step 10 — the gates are the ONLY thing that flips it
if all(g.passed for g in gates):
    client.set_payload(collection, payload={"is_current": True},
                       points=Filter(must=[FieldCondition(key="run_id",
                                                          match=MatchValue(value=run_id))]))
    run.published_at = now()          # recorded only after the call returns

# every tool injects this server-side, always
must += [FieldCondition(key="is_current", match=MatchValue(value=True))]
```

The filtered `set_payload` is not atomic, so it must be idempotent and retried, and
`published_at` is written only once it returns. For a full-corpus rebuild prefer the genuinely
atomic path: write a new collection, then swap a collection alias in one
`update_collection_aliases` call.

### I8 · Every asserted code is verified against the page it is cited on

```python
# runner/answer.py — the answer template cannot interpolate an unverified code
for code in codes_in_draft:
    v = verify([code], [cited_page_id])[code]
    if v.status == "present":    render(code)
    elif v.status == "unverifiable":  render(code, badge="read from image, not text-verified")
    else:                        reject_draft(code, v.present_instead)
```

Verification is per `(claim, page)`, not per claim — the worked trace in the spec verifies
`p001` while citing `p001–p002`, which would let a code from the neighbouring page through.

---

## 2 · The failure-mode catalogue

Every path to a confidently wrong answer we could find, with the guard that closes it and
the test that keeps it closed. **This table is the definition of done.**

| # | Failure | How it happens | Guard | Test |
|---|---|---|---|---|
| F1 | `lookup` returns the wrong page as exact | `MatchText` is any-order (S01) | I3 phrase-only | `SF 1.1A → exactly 1` |
| F2 | `verify` confirms a code that is not on the page | same filter reused (S01) | one `exact_filter` | `verify('SF 1.1A', p008) → absent` |
| F3 | Abstains on a label that *is* printed | no-space tokenisation (S04) | I3 variants | the 8 compact labels |
| F4 | *"That part doesn't exist"* about a scanned page | `not_searchable` collapsed into `not_found` (S05) | `has_text` facet + I5 | scanned doc → `not_searchable` |
| F5 | Follows a cross-reference to the wrong page | `printed_page_no` is model-read, unverified (S12) | `get_label()` precedence, `label_verified`, ambiguous → list | misread label → flagged, never silent |
| F6 | Cites a page for a code that is on its neighbour | window-fold attention bleed (S08) | per-page `grounded_rate`, reattribution, I8 | code moved → `moved_from` recorded |
| F7 | Every page number shifted by one | offset error (S06) | I4 | synthetic 3-window fixture |
| F8 | Searches a subset believing it searched the chapter | two `section_id`s for one section (S03); server-held scope (N2) | canonical key + carry-in + `series_id`; stateless + echo `effective_scope` | straddling-section fixture |
| F9 | Cites a superseded revision as current | no lifecycle (S17) | `is_current` injected by default | two revisions indexed |
| F10 | Silent recall loss | filter on a nested field (S02) | I6 | unknown key → 400 |
| F11 | Cache serves output from a different model or prompt | key omits them; `-latest` alias (S21, N4) | window-composed key incl. resolved version; refuse aliases at boot | key changes when prompt changes |
| F12 | Totals double; stale pages stay findable | no point-id rule (S17) | I1 + delete by `run_id` | re-ingest twice → same count |
| F13 | A window truncates and loses 30 pages | unbounded output (S06, S12) | output-budget ladder; `MAX_TOKENS` → bisect | oversized window bisects |
| F14 | A model-invented code becomes findable | model output in a lexical index | I2 | hallucination test |
| F15 | A code is invisible because it was cropped away | undefined segmentation stage (N1) | `text` always from the **full** page | crop fixture → full text indexed |
| F16 | A near-miss code presented as the answer | "neighbours" implemented as similarity (S07) | `present_instead` = prefix filter on *observed* tokens, capped, never a distance | `K73` on a K78 page → `absent` + `present_instead` |
| F17 | A half-finished run answers queries | no publish gating (S25) | I7 `is_current` | kill an ingest mid-run → 0 pages queryable |
| F18 | Unbounded spend | caps stated in prose, not in signatures | `read ≤ 3` (the spec's own number), `fetch ≤ 5` pages and ≤ 12 MP, `dpi ∈ {150,220,300,400}`, `dpi > 220` requires a `region` — each a **typed 400**, never a clamp | over-budget → `fetch_budget_exceeded` naming the bound |
| F19 | A second question about the same pages returns the first answer | `read` cache keyed on the page hash alone (N4) | `read_key` includes the question | same pages, new question → cache miss |

Two properties of this table are worth stating. First, **every row degrades to a visible
state** — an abstention, a flag, a 4xx — never to a plausible wrong page. Second, no row is
closed by "the model will get it right"; each is closed by a deterministic check.

---

## 3 · The test pyramid, and the fixture that makes it cheap

The decisive move: **freeze one real extraction as a fixture**, so everything downstream of
the paid call is testable forever at zero cost.

```
data/fixtures/TC1E-SF/
  raw_window_1.json      the VERBATIM WindowOut for pages 1-30, as returned
  raw_window_2.json      pages 31-55
  text.json              PyMuPDF text per page, from the pinned extractor
  expected.json          the acceptance table below
```

One paid ingest buys a permanent test corpus. Derivation, stitching, the offset, the index
config, every tool and the whole agent loop are then testable with no Gemini and no PDF.

| Level | What it tests | Needs | Runtime |
|---|---|---|---|
| **L0** | pure functions: `tok`, `variants`, offset, label normalisation, stitching | nothing | < 1 s |
| **L1** | derivation over the frozen `raw_window_*.json` → 55 page records | fixture | < 5 s |
| **L2** | index contract: the acceptance table against an ephemeral Qdrant | docker | < 30 s |
| **L3** | **adversarial abstention** — the safety test | docker | < 60 s |
| **L4** | the worked trace and the failure branch, end to end | docker + Gemini | minutes |
| **L5** | canary on a held-out document nobody tuned against | full stack | manual |

### L2 · The acceptance table — absolute, not comparative

Measured on this corpus, so these are the expected values, not a baseline to compare with:

```
lookup("SF 1.1A")                       → exactly 1 page      (MatchText would give 3)
lookup("SF 5.5b")                       → exactly 1 page      (MatchText would give 2)
lookup("SF 121.1")                      → 1 page              (the compact-label variant)
lookup("EAO 84-5140.0020")              → 10 pages
lookup("B&R X20SI4100")                 → 54 pages
lookup("3")            unscoped         → weak:true, needs_scope   (matches 120 of 146)
lookup("alarm 152")                     → 0 by phrase → the ladder, never a bare not_found
verify("SF 1.1A", [p008])               → absent               (tokens present, phrase not)
scanned document                        → not_searchable, never not_found
```

### L3 · The adversarial abstention eval — the one that would catch a real injury

```python
def test_near_miss_codes_never_answer():
    """Sample 100 codes one character off real ones from the 8,414 near pairs."""
    for fake in near_misses(n=100):
        r = lookup(fake)
        assert r.hits == []                       # no exact hit
        assert r.status in ("not_found", "not_searchable")
        for n in r.present_instead.values():      # neighbours, if offered
            assert n != fake                      # never returned AS the match
```

If one assertion in this test ever fails, the system has produced the injury the whole
design exists to prevent. It runs in CI on every commit.

Add a **conformance test** that greps for banned constructs, because these are the mistakes
a well-meaning contributor makes: `MatchText` in `serve/`, any fuzzy/similarity library in
`requirements.txt`, any `score` field in a response model, a model id ending in `-latest`.

---

## 4 · Two kinds of gate

**Publish gates** decide whether a document becomes visible. A document is published
atomically or quarantined — half a manual in the index makes every coverage measure a lie.

| gate | metric | threshold | action |
|---|---|---|---|
| `window_coverage` | pages with an S2 record ÷ page count | must be 1.0 after retries | **block** |
| `offset_check` | windows passing I4 | all | **block** |
| `grounded_rate` | document median | ≥ 0.8 | **block**, hold for review, list worst pages |
| `text_coverage` | pages with `has_text` ÷ total | — | flag `mostly_scanned`, never block |
| `label_monotonic` | printed labels non-decreasing | — | flag `label_conflict` |

**Answer gates** live in the runner and decide whether a draft may be shown:

- no code may be asserted that `verify` did not return `present` for *that page* (I8);
- the words *"not in these documents"* are forbidden while
  `unsearchable_pages_read < unsearchable_pages_in_scope` — the honest wording names the
  gap: *"not found in the searchable text; N image-only pages were not examined"*;
- a page whose `text_trust != ok` may only support an answer after the zoom-and-re-read
  double check, and its codes carry the *read from image* badge.

---

## 5 · Build order — prove the design before spending money

The ordering principle: **every correctness property that can be proved without a model
call is proved first.** M1 closes the three worst failure modes with zero API spend.

| | Milestone | Delivers | Acceptance | Spend |
|---|---|---|---|---|
| **M0** | Spec fixes | S01–S07, N1–N2 written into the plan docs; decisions closed | a builder can implement §6 without guessing | none |
| **M1** | `core/` + L0/L2 | record, `exact_filter`, `tok`, `variants`; ephemeral Qdrant; **hand-written page text, no PDF** | F1 F2 F3 F10 F14 F16 closed; the acceptance table passes on synthetic text | **none** |
| **M2** | `ingest/` one PDF | manifest, probe, windows, extract, derive, embed, index, gates | 55 points; I1 I4 hold; **fixture frozen** | S2 + embed, once |
| **M3** | `lookup` + `verify` | typed absence, `present_instead`, `unverifiable` | the full acceptance table + **L3 abstention eval** on real text | none |
| **M4** | `skim_pages`, `fetch`, `resolve` | triage rows, `exclude`, `next`, caps, auth, cost | the trace's narrowing step returns p001/p002; 401 without a token | none |
| **M5** | skims + runner | document/section rungs, browse mode, the loop | the worked trace completes in **one paid call**; the failure branch abstains with coverage numbers | read only |
| **M6** | `read`, revisions, jobs | per-page schema, `is_current`, resumable ingest | F9 F12 F13 closed; a 1,440-page ingest survives a kill at window 700 | read |

**M1 is the whole proof and it costs nothing.** Insert three synthetic pages whose text you
control — one containing `SF 1.1A`, one containing the tokens `sf`, `1`, `1a` scattered, one
printing `SF121.1)` — and the phrase-vs-any-order question, the compact-label question and
the hallucination question are all settled before a single PDF is opened.

---

## 6 · Runtime degradation policy

Fail-proof includes failing loudly at the right moments. Each row is a refusal, not a
best-effort fallback:

| condition | behaviour |
|---|---|
| Qdrant unreachable | `503`, retryable — **never** an empty result |
| Gemini unreachable | `503` on `read`; the free tools keep working |
| index schema ≠ pinned config | **refuse to serve** at boot (I6) |
| embedding model ≠ collection fingerprint | **refuse to upsert**; a model change is a new collection + full re-embed + alias swap |
| configured model id ends in `-latest` | **refuse to start** (F11) |
| a document's `grounded_rate` collapses | mark it `text_untrusted`; its pages count as unsearchable for `lookup`, and `verify` returns `unverifiable` |
| per-caller `read` quota exhausted | typed `budget_exhausted`, not a silent truncation |
| an over-budget `fetch` | typed `400 fetch_budget_exceeded {limit, requested}` — **never** a silent dpi clamp or a truncated page list |

Observability that makes the above visible rather than mysterious: Prometheus gauges for
`ingest_grounded_rate_median{doc_id}` and `ingest_gate_failures_total{gate}`; a `GET
/runs/{run_id}` record carrying `{state, step, windows_done, windows_total, pages_indexed,
gate_results, failed:{step, reason}}`; and the triage marks (*query → page → relevant?*)
written to telemetry as free evaluation data.

**Cost goes in the audit log, not the response body.** One append-only line per `read` and
`fetch` — `(user_id, run_id, session_id, tool, page_ids, dpi, input_tokens, output_tokens,
cache_hit, latency_ms)` — with the `user_id` taken from the propagated identity, never a
client-supplied field. The agent gets one integer, `reads_remaining`, against a hard cap.
A `usd_estimate` in the envelope is a weak lever mis-sold as a strong one: the real budget
control is the server-side cap plus prompt discipline, and padding the `read` envelope puts
noise beside the verification stamps, which are the fields that must not be missed.

---

## 7 · What this plan does not promise

Stating the residual risk is part of being fail-proof, because an overclaimed guarantee is
itself a failure mode.

- **Recall is not guaranteed.** A page whose summary omits the one line that mattered can be
  triaged away. Mitigations: the `uncertain` pool, "do not filter a small set", and
  `codes_in_text` as a hard signal — but a miss remains possible, and it surfaces as an
  honest abstention rather than a wrong page.
- **A scanned page's codes are never text-verified.** They come back `unverifiable` forever.
  The zoom-and-re-read double check reduces transcription error; it does not eliminate it.
  The honest badge is the deliverable, not certainty.
- **The extractor is the single point of truth for exact search.** If PyMuPDF misses text on
  some malformed PDF, `lookup` is blind there. Detection: `grounded_rate` collapse. That is
  a diagnostic, and F6's guard turns it into an action.
- **`grounded_rate ≥ 0.8` is a chosen threshold, not a derived one.** Measure the
  distribution on the pilot corpus in M2 and set it from data before trusting it as a gate.
- **Multi-tenancy is out of scope, deliberately.** Nothing in the specification posits more
  than one customer's documentation, and a server-injected `tenant_id` filter would be
  invented scope. If a second customer ever shares an instance, this becomes a blocking
  finding rather than a residual risk — and the honest statement today is that the corpus is
  single-tenant and the auth boundary is the whole service.
- **Every safety rule that lives in the agent's system prompt is unenforceable if the tool
  surface is open.** The MCP server can be pointed at by any compliant client, which will
  bring its own prompt — so the tri-state triage, the mandatory `verify` before asserting a
  code and the abstention wording are advisory there. Only the server-side gates (I5, I7, I8,
  the caps) survive a hostile or careless client. Either ship the runner as the only
  supported entry point, or accept that the prompt-level rules are best-effort and put the
  answer gate behind the API rather than in the prompt.

---

## The plan in one line

> **Make every rule an assertion, every path to a wrong answer a row in a table with a test
> beside it, and prove the exact-match surface on synthetic text before spending a cent —
> then the only failures left are the visible ones.**
