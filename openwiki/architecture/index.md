# Files

- [Configuration and Boot Self-Check](configuration-and-boot.md) - How a VSIR process is configured from the environment alone, which values are pins in code instead, and how the shared boot self-check refuses to start rather than serve a partially correct index.
- [Replay and Live Execution Modes](execution-modes.md) - How one environment variable selects both the extraction and the embedding backend, what the four content-addressable cache keys are made of, and how frozen fixtures let the whole pipeline run without a credential or a bill.
- [System Architecture Overview](overview.md) - End-to-end shape of VSIR — an eleven-step VLM ingest pipeline turns PDF pages into Qdrant points carrying one dense and two sparse vectors, and eight tools serve them through a single dispatcher shared by HTTP, MCP and the CLI.
- [External State and Storage](state-and-storage.md) - The two Qdrant collections and the record kinds inside them, the document store of source PDFs, the upload spool, the fixture directories, and the in-process raster cache that is deliberately never persisted — with the typed refusal each absence produces.
