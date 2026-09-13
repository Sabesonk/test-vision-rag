---
type: subsystem
title: Search, Fusion and Ranking
description: The one candidate function behind every narrowing rung and the flat search surface — three branches, reciprocal rank fusion over ranks only with no similarity magnitude anywhere, query decomposition before embedding, and how scope versus content filters decide which typed absence a caller is told about.
tags: [search, fusion, rrf, ranking, sparse, dense, scope, absences]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-12T16:01:50.652Z
sources:
  - id: openwiki-source-2205ae93add6598628c21601
    resource: repo://backend/vsir/serve/app.py
  - id: openwiki-source-b7216abafad3237d37d98418
    resource: repo://backend/vsir/serve/retrieval.py
  - id: openwiki-source-46bbcaacf27e1545d30fd654
    resource: repo://backend/vsir/serve/tools/lookup.py
  - id: openwiki-source-ce92203bf6555d1c87e2f2f1
    resource: repo://backend/vsir/serve/tools/skim.py
generated: { by: "claude-code", at: "2026-09-12T16:01:50.652Z" }
---

# Search, Fusion and Ranking

One function runs the search. The three narrowing rungs are three *renderings* of the list it
returns — truncated to a limit, grouped by document, grouped by section — and the flat search
surface calls the same function with the fusion's knobs exposed. There is no second search, no
second fusion and no second scope filter: if the diagnostic surface ranked differently from the
page rung, one of the two would be lying about what the index does.

## The surface, end to end

Four callers, one dispatcher, one tool table. Seven of the eight tools are free and touch no model
at all: only `read` spends, and only it needs a credential.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TB
    MCPC["MCP client<br/>stdio + SSE"]
    HTTPC["HTTP client"]
    CLIC["CLI — vsir tool"]
    UIC["Console / React<br/>same-origin proxy"]

    MCPC --> DISPATCH
    HTTPC --> DISPATCH
    CLIC --> DISPATCH
    UIC --> DISPATCH

    DISPATCH["vsir.serve.app.dispatch<br/>one tool table · bearer auth<br/>one envelope · one audit line"]

    subgraph eight ["The eight tools — POST /tools/name"]
        direction LR
        SD["skim_documents · NARROW<br/>which binder?"]
        SS["skim_sections · NARROW<br/>which chapter?"]
        SP["skim_pages · NARROW<br/>which page?"]
        LK["lookup · JUMP<br/>exact phrase, a set"]
        RS["resolve · FOLLOW<br/>printed label to page_id"]
        VF["verify · CHECK<br/>claim by page"]
        FT["fetch · LOOK<br/>image / text / summary"]
        RD["read · COMPREHEND<br/>3 pages at 220 dpi · SPENDS"]
    end

    DISPATCH --> SD
    DISPATCH --> SS
    DISPATCH --> SP
    DISPATCH --> LK
    DISPATCH --> RS
    DISPATCH --> VF
    DISPATCH --> FT
    DISPATCH --> RD

    SEARCH["POST /search<br/>the flat surface, knobs exposed<br/>deliberately not a ninth tool"]
    ASK["POST /ask<br/>the agentic runner<br/>the only surface that answers"]
    HTTPC --> SEARCH
    HTTPC --> ASK
    ASK -->|"calls the eight tools<br/>through the same dispatcher"| DISPATCH

    CAND["_candidates<br/>the one search"]
    EXACT["exact_filter<br/>the one exact-match path"]

    SD --> CAND
    SS --> CAND
    SP --> CAND
    SEARCH --> CAND
    LK --> EXACT
    VF --> EXACT
    RS --> EXACT

    QDRANT[("Qdrant pages collection<br/>stem plus embed dim")]
    CAND --> QDRANT
    EXACT --> QDRANT
    CAND --> EMB["embedding backend<br/>Gemini, or StubEmbedder under replay"]
    FT --> RASTER["PyMuPDF re-render on demand<br/>in-process LRU, never persisted"]
    RD --> GEM["Gemini VLM<br/>the only dependency that costs money"]

    style RD fill:#7c2d12,color:#ffffff
    style GEM fill:#7c2d12,color:#ffffff
    style CAND fill:#1e3a5f,color:#ffffff
    style EXACT fill:#1e3a5f,color:#ffffff
```

And the pipeline inside `_candidates` — every refusal typed, and every one of them reached before
a round trip is spent:

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TB
    IN["query · images · scope · exclude<br/>weights · k · phrases · page range"]
    IN --> G1{"words or<br/>a photograph?"}
    G1 -- neither --> X1["ToolError query_required"]
    G1 -- yes --> ES["effective_scope<br/>inject is_current = true"]
    ES --> G2{"every filter key<br/>in INDEXED?"}
    G2 -- no --> X2["400 filter_unknown_key<br/>never an unindexed scan"]
    G2 -- yes --> DEC["decompose<br/>a word containing a digit is an identifier<br/>reset K158 becomes K158 plus reset"]

    DEC --> FA["scoped filter — facets only<br/>the denominator absence selection reads"]
    DEC --> FB["narrowed filter — scope<br/>plus exact_filter per identifier<br/>plus require and exclude phrases<br/>plus must_not over point ids"]

    FA --> STATS["scope_stats<br/>pages · searchable · pages_no_text"]
    FB --> TOT["count_exact — total"]

    FB --> B1["dense branch<br/>embed prose plus images<br/>at most 4 images, one Content"]
    FB --> B2["lexical branch<br/>sparse query vector<br/>1.0 per distinct term"]
    FB --> B3["captions branch<br/>the same query vector"]

    SKIP["branches_skipped<br/>no_query_text · nothing_left_to_embed · weighted_zero"]
    B1 -.-> SKIP
    B2 -.-> SKIP
    B3 -.-> SKIP

    QP["query_points, limit = BRANCH_DEPTH = 50<br/>with_payload = ROW_PAYLOAD<br/>the text field is never loaded"]
    B1 --> QP
    B2 --> QP
    B3 --> QP

    QP --> RRF["rrf — fuse on ranks only"]
    RRF --> FUSED["Candidates.fused<br/>untruncated and deterministically ordered"]

    FUSED --> R1["skim_pages<br/>truncate to limit"]
    FUSED --> R2["skim_documents<br/>group by document"]
    FUSED --> R3["skim_sections<br/>group by section"]
    FUSED --> R4["POST /search<br/>offset plus limit plus include"]

    style X1 fill:#7f1d1d,color:#ffffff
    style X2 fill:#7f1d1d,color:#ffffff
    style RRF fill:#1e3a5f,color:#ffffff
    style DEC fill:#1e3a5f,color:#ffffff
```

## Three branches

Inside the scope and minus any exclusions, three rankings are produced:

- **dense** — the fused image-and-text page vector;
- **lexical** — sparse, over the page's extracted text;
- **captions** — sparse, over the model's generated summaries and topics, weighted lower.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart LR
    PAGE["One Qdrant point is one page<br/>point id = uuid5 of the page id"]

    PAGE --> V1
    PAGE --> V2
    PAGE --> V3
    PAGE --> PL

    V1["dense — named vector, cosine<br/>one multimodal embedding of the<br/>150 dpi raster, the doc title, the section titles,<br/>a part per language summary, the topics,<br/>the codes, and the first 2000 characters of text"]

    V2["lexical — sparse<br/>BM25 tf over the extracted text<br/>avg_len 256 · weight 1.0"]

    V3["captions — sparse<br/>BM25 tf over the generated summaries<br/>and topics, deduped against the printed text<br/>avg_len 16 · weight 0.4"]

    PL["payload — the 16 INDEXED keys"]
    PL --> F1["14 filterable facets<br/>doc_id revision is_current doc_type<br/>subjects tags page_kind lang page_no<br/>section_id series_id has_text<br/>text_trust run_id"]
    PL --> F2["2 text indexes, not filterable<br/>text and vlm_codes<br/>WORD tokenizer · lowercase<br/>phrase_matching · min_token_len 1<br/>reachable only through lookup and verify"]

    BM["stored value = the BM25 tf component<br/>k1 = 1.2 · b = 0.75<br/>query value = 1.0 per distinct term<br/>idf supplied by Qdrant at query time"]
    V2 --> BM
    V3 --> BM
    BM --> WHY["so ingesting a document changes no stored value:<br/>avg_len is a released pin and the length is the page's own.<br/>Correcting a pin is a SPARSE_VERSION bump, not a tweak"]

    style V1 fill:#1e3a5f,color:#ffffff
    style V2 fill:#14532d,color:#ffffff
    style V3 fill:#14532d,color:#ffffff
    style F2 fill:#4c1d95,color:#ffffff
```

Each branch's list is in rank order, and the position in that list is the whole input to the
fusion.

**A branch runs only when it has an input, and says so.** An image-only query has no text to build
a sparse vector from, so the two sparse branches are skipped and the fusion degenerates to the
dense ranking with every row reporting only the dense surface — the agent can see the evidence is
weaker than a lexical hit. A query that decomposes to identifiers alone has nothing left to embed
once the code has gone to the phrase filter, so the dense branch is skipped for the same reason:
embedding the code anyway would be exactly the blurring that decomposition exists to prevent. The
two conditions are exhaustive over "words, a photograph, or both", so every query reaches at least
one branch.

**A branch weighted zero is not run at all** rather than run and discarded. The fusion already
ignores it, so no ranking changes — what changes is that a dense-only search stops paying for two
sparse round trips whose results are thrown away, and the reported branch list then means *what
actually ran*.

## Decomposition happens before anything is embedded

Exact identifiers are split out of the query **first**: a query like `reset K158` sends the code
to the phrase filter over the single exact code path and only `reset` to the embedding. A printed
code blurred into a high-dimensional average is a code that ranks pages which merely *resemble*
the one printing it, and the guarantee is that a returned code is a printed one.

The rule is **not a grammar**: a word is an identifier if it contains a digit, using the same
code-like predicate the rest of the system uses, imported rather than re-stated. No per-corpus
regex decides which shapes of code a caller may search for. The crudeness is affordable in this
direction because a word wrongly called an identifier is asked of the *stricter* surface — the
failure is a narrower answer that says so, never a wrong page.

Adjacent words are **not** joined, so a label like `SF 1.1A` decomposes to an identifier and a
prose word, and the index is asked for the contiguous ordered phrase — the same phrase an exact
lookup would match with, one token shorter.

## Fusion is ranks only

```
total = Σ  weight(surface) / (k + rank(surface))
```

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TB
    D["dense list<br/>p12, p40, p7, ..."] --> F
    L["lexical list<br/>p40, p3, p12, ..."] --> F
    C["captions list<br/>p7, p40, ..."] --> F

    F["total = sum of weight(surface) / (k + rank(surface))<br/>k = 60 · dense 1.0 · lexical 1.0 · captions 0.4<br/>the position in the list is the whole input"]

    F --> T["ties break deterministically<br/>1. total<br/>2. best per-surface rank<br/>3. point id"]
    T --> OUT["FusedRow"]

    OUT --> P1["rank — the ordinal, 1-based — published"]
    OUT --> P2["surface_ranks — dense 1st, lexical 7th — published"]
    OUT --> P3["why — the branches that contributed — published"]
    OUT --> P4["total — never returned<br/>private, deliberately not named score,<br/>and a conformance grep fails the build on the field name"]

    P4 --> WHYNOT["a magnitude invites a threshold,<br/>a threshold turns ranked ninth into no results,<br/>and a fabricated abstention is the one failure<br/>this system is built to make impossible"]

    style F fill:#1e3a5f,color:#ffffff
    style P4 fill:#7f1d1d,color:#ffffff
    style WHYNOT fill:#7f1d1d,color:#ffffff
```

Ranks are the only input; a similarity value never enters the arithmetic, so there is nothing to
leak into a response and no caller can mistake a fused number for a confidence. The accumulator is
private, is deliberately not named `score`, and is **never returned** — a number that escapes into
a response is a score somebody eventually displays, and a conformance grep fails the build on the
field name.

What *is* published is an **ordinal rank** and, on the diagnostic surface, each branch's own
ordinal — the honest form of *why is this here*: dense put it first, lexical seventh, captions
never found it. Per-surface ranks are kept rather than just which surfaces hit, because they are
what the fusion actually consumed and therefore what makes a weight change explicable.

**Ties break deterministically**: by total, then by best per-surface rank, then by point id. The
earlier implementation sorted on the total alone and left equal rows in insertion order, which
breaks the requirement that the same query return the same rows in the same order.

A surface weighted zero contributes nothing, not even its presence in the row's surface list.

## The three rungs are three renderings

`skim_pages` truncates the fused list to a limit; `skim_documents` and `skim_sections` group it by
document and by section. Grouping rather than re-searching is also what stops one chatty document
occupying every slot and burying the binder that answers.

The aggregate rows carry **no page id** — they answer *which binder?* and *which chapter?* and
hand back a scope to descend into. They do carry a preview thumbnail of the group's best-ranked
matched page, and a document row carries its searchable ratio.

That ratio is the point of the document rung: **a binder nothing can be found in by text is
returned anyway**, at a zero ratio with no matched pages, because the alternative is that it
disappears from the answer set in silence and the agent concludes the part is not in a binder
nobody looked in.

## Image queries

Three rules, each stated in the response rather than implied: no instruction prefix when the query
is multimodal; an image-only query runs the dense branch alone; and **an image can never reach the
exact surface** — there is no image parameter on the exact tools and none on the identifier path
here. A photograph may *find* a page; it may not assert what is printed on one.

## Scope versus content decides which absence is reported

Two filters are built, and the difference between them chooses the caller's next move:

- the **scope** filter carries the caller's facets and is the denominator that absence selection
  reads;
- the **branch** filter adds content conditions — the decomposed identifiers, a required phrase —
  and is what the branches actually run under.

A *content* filter that matched nothing has not emptied the scope; it has **searched** it. Putting
a required phrase into the scope filter would report a scope of forty readable pages as unasked and
send the caller off to widen a scope that was never the problem.

Absence selection then runs in a fixed order:

1. **`found_only_in_superseded`** first — it is the only one of the four that is not an
   abstention. The others say "the current corpus does not have this"; this one says "a revision
   that is no longer current does". Both statuses it outranks would be *wrong* rather than merely
   less specific.
2. **`out_of_scope`** when the scope selected no page — the corpus was never asked.
3. **`not_searchable`** when it was asked and nothing was readable.
4. **`not_found`** otherwise.

The superseded probe fires **only where the scope itself is empty**, and it reads the control
plane rather than the page index. In the page index a non-current point is one of two completely
different things — a revision that was published and later superseded, or a run that never passed
its gates — and they are indistinguishable there because the payload records the flag and not its
history. Naming the second kind would disclose a half-ingested revision through the one status
that is supposed to be about the past, at exactly the moment an operator is least able to tell the
report is wrong. So the revisions the tool will name are the revisions a gate let through, and
nothing else.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TB
    E["the rung returned no rows"] --> A{"did the scope select<br/>any current page?"}
    A -- no --> S{"does a published, superseded<br/>revision match?<br/>read from the control plane,<br/>never from the page index"}
    S -- yes --> R1["found_only_in_superseded<br/>not an abstention: a revision that is<br/>no longer current does have this"]
    S -- no --> R2["out_of_scope<br/>the corpus was never asked — widen"]
    A -- yes --> B{"any page in scope<br/>with text that may be believed?"}
    B -- no --> R3["not_searchable<br/>asked, and nothing was readable —<br/>escalate to vision"]
    B -- yes --> R4["not_found<br/>asked, readable, and the answer is no"]

    NOTE["a content filter that matched nothing has searched<br/>the scope, not emptied it — which is why a required<br/>phrase goes to the branch filter and never to the scope"]
    NOTE -.-> A

    style R1 fill:#14532d,color:#ffffff
    style R2 fill:#78350f,color:#ffffff
    style R3 fill:#78350f,color:#ffffff
    style R4 fill:#78350f,color:#ffffff
```

## The flat search surface

The same retrieval with the knobs exposed, for two consumers: an operator asking *why did page 40
come third?*, and a caller that wants this service as a search engine and will do its own
reasoning.

It collapses the ladder — a row can carry its summary, extraction, topics, codes, labels and
sections beside its rank, so a caller that would otherwise run a skim then a fetch runs neither.
That is why it may return page text where a triage row may not: a triage row withholds content so
an agent cannot answer from the search result instead of choosing a page and paying for it, while
a caller that reached this path has declared it is doing its own reasoning, and withholding text
would only make it fetch the same bytes twenty-five times. The remaining bound is size, not trust:
each row is capped and states when it truncated.

What it does **not** collapse is the honesty of the row: every row still states its text trust and
whether it has text, because on a scanned page the text is empty *because nobody could read the
page* rather than because the page is blank. Codes on these rows are the model's **claims**, never
verdicts.

It is deliberately **not a ninth tool**: the eight are an agent's moves, and a knob is not a move.
Neither of this surface's consumers is choosing a move. And it still publishes **no score**.

## Related pages

- [Embedding and the Three Retrieval Surfaces](../ingestion/embedding-and-sparse-surfaces.md) — how the three vectors are built
- [The Eight Tools and the Dispatcher](tool-surface.md) — the rungs as moves
- [Typed Results and Refusals](../concepts/typed-results-and-refusals.md) — what each absence tells a caller to do
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — the facets a scope may filter on
