# Files

- [Exact Match and Claim Verification](exact-match-and-verification.md) - The single exact-match code path — tokenisation mirroring Qdrant's WORD tokenizer, three re-spaced variants, phrase filtering — and the per-(claim, page) verification built on it, with its three verdicts and the bounded present_instead disclosure.
- [Page Model and Index Schema](page-model-and-index-schema.md) - The page as the addressable unit — deterministic identifiers that make a re-ingest overwrite rather than double, the two-zone page record, the single INDEXED dict that creates gates and asserts the payload schema, and the text-trust ladder.
- [Typed Results and Refusals](typed-results-and-refusals.md) - Why nothing found is never an empty 200 — the six-value status enum with its four distinct absences, the two envelope families, the single refusal shape published in the schema, and caps that refuse by name rather than clamping or truncating.
