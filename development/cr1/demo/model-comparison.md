# Gemini model comparison for this workload

Pricing fetched live from <https://ai.google.dev/gemini-api/docs/pricing> on **2026-09-10**.
Workload is the 26-document demo slice in `demo-corpus.csv`: **2,300 pages · 118 S2 windows ·
144 API calls · 9,117,432 VLM input tokens · 2,321,900 VLM output tokens** (335 tok/page × the ×3
thinking allowance), plus 2,300 page embeddings.

## Cost of the whole demo slice, per model

| model (S1 + S2) | batch | standard | 2027 standard | note |
|---|---:|---:|---:|---|
| **Gemini 3.8 Flash** ← pinned | **$8.03** | **$16.05** | $31.60 | doubles 1 Jan 2027 |
| Gemini 3.7 Flash | $8.03 | $16.05 | $31.60 | doubles 1 Jan 2027 |
| Gemini 3.6 Flash | $8.03 | $16.05 | $31.60 | doubles 1 Jan 2027 |
| Gemini 3.5 Flash | $17.54 | $35.08 | $35.08 | |
| Gemini 3.5 Flash-Lite | $4.52 | $9.05 | $9.05 | |
| Gemini 3.1 Flash-Lite | $3.13 | $6.27 | $6.27 | |
| Gemini 3.1 Pro Preview | $23.30 | $46.60 | $46.60 | ≤200k ctx tier |
| Gemini 2.5 Pro | $17.56 | $35.12 | $35.12 | ≤200k ctx tier |
| Gemini 2.5 Flash | $4.52 | $9.05 | $9.05 | |
| Gemini 2.5 Flash-Lite | $1.17 | $2.35 | $2.35 | cheapest |

Every row includes the same **$0.25 batch / $0.51 standard** of embeddings, which do not vary with
the VLM.

**The whole spread is $1.17 → $23.30.** Twenty-fold in ratio, twenty-two dollars in absolute terms.
Cost cannot rationally decide this.

## Embeddings — a separate and more consequential decision

| model | text $/1M | image | batch |
|---|---:|---:|---:|
| **Gemini Embedding 2** ← pinned | $0.20 | $0.45/1M · $0.00012/image | $0.10 / $0.225 |
| Gemini Embedding | $0.15 | — (no image tier published) | $0.075 |

The slice's embedding bill is **$0.51 standard**. Financially irrelevant; operationally it is the
*expensive* switch. `embed_model` is half of the §6.6 index fingerprint, so changing it forces a
new collection, a full re-embed and an alias swap — never an in-place mix (`vsir ingest` refuses
`embed_fingerprint_mismatch`). Changing the **VLM** costs only a re-bill of S1/S2, because
`extract_key` carries the model id and the receipts are content-addressed.

So: treat the VLM as cheap to revisit and the embedder as pinned for the life of the collection.
D4 also depends on the embedder accepting interleaved image+text in one `Content` and honouring
`output_dimensionality=1536`, which `gemini-embedding-2` was verified to do on the live run.

## What should actually choose the model

Not price. **`grounded_rate`** — the share of model-emitted codes the page's text layer backs.
That number *is* the measure of whether a model misreads identifiers, which is the one failure
this product exists to prevent, and the pipeline already computes it per page and blocks publish
below a 0.8 median (§11.1).

The bake-off is cheap because the pilot is small:

| | |
|---|---:|
| `TC1E-SF`, 55 pp, 2 windows, on Gemini 3.8 Flash | **$0.23** standard |
| the same on four candidate models | **< $1.00** |

Procedure, using machinery that already exists:

```bash
for M in gemini-3.8-flash gemini-2.5-flash gemini-3.1-flash-lite gemini-2.5-flash-lite; do
  VSIR_VLM_MODEL=$M VSIR_ALLOW_PAID=1 \
    vsir ingest data/source/TC1E-SF.pdf --doc-id TC1E-SF --revision 1.3 --vlm gemini
  vsir eval acceptance            # the §12.3 table in data/fixtures/TC1E-SF/expected.json
done
```

`expected.json` is normative and was written before any ingest, so it judges each model without
re-baselining. Compare `grounded_rate` median, `code_precision` and `abstention_correctness`
(the D11 gates, both required to be **1.00**) across the four.

**Caveats worth stating rather than guessing at.** I have not evaluated the Lite tiers for
OCR-grade reading of one-character-apart identifiers, nor for strict `response_schema` adherence
— both are load-bearing here and both are exactly what the bake-off measures. The Pro rows are
priced at the ≤200k context tier; at ~3,960 tokens per page at 220 dpi a full 30-page window is
**~118k input tokens**, so it stays inside that tier, but with less headroom than it appears.

## Recommendation

Keep **Gemini 3.8 Flash** pinned for the demo — $16.05 standard, $8.03 batch, and it is the
configuration whose live path is already proven end to end. Run the four-model bake-off on the
55-page pilot for under a dollar *before* the full slice, and let `grounded_rate` decide whether
a Lite tier is good enough to halve a bill that is already immaterial.
