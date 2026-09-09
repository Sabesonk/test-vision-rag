# Implementation Roadmap: New Pipeline

This document outlines the implementation strategy for the new pipeline, focusing on the complete replacement of the existing ingestion and retrieval logic with the new structural text-index and agentic retrieval architecture.

## 1. Core Principles
- **No Curated Lists:** Exact search is now a full-text index over extracted text.
- **Verification by Construction:** The index is built from PyMuPDF text, making hallucinated identifiers impossible to retrieve.
- **Image-First Reasoning:** Reasoning happens over page rasters; text is for triage and citation.

## 2. Implementation Phases

### Phase 1: Ingestion Pipeline (The Foundation)
- **Schema Update:** Implement the new `S2` response schema (`PageOut`, `SectionRef`, `WindowOut`).
- **Text Indexing:** Replace the existing `entity_keys` allowlist with two full-text indexes: `text` and `vlm_codes` (opt-in).
- **Health Metrics:** Implement the `grounded_rate` diagnostic to localize text extraction issues.
- **Deterministic Caching:** Implement SHA-256 content-addressable caching for VLM page outputs.

### Phase 2: MCP Tool Surface
- **Tool Development:** Implement the 8 core tools defined in `AGENTIC-RETRIEVAL.md`.
- **State Management:** Create the `RetrievalState` manager for the "Zoom Ladder" scope.
- **Cost/Latency Safeguards:** Implement the 3-page cap for `read`, DPI-budgeting for `fetch`, and image caching.

### Phase 3: Agentic Loop Integration
- **System Prompting:** Design the agent's system prompt to enforce the tri-state triage (relevant/uncertain/irrelevant) and mandatory fallback to `uncertain` before widening scope.
- **Loop 0-5 Implementation:** Integrate the logic for the six retrieval loops (Triage, Transcription Correction, Claim Verification, etc.).

## 3. Deletion Targets (Cleanup)
We will remove the following legacy components:
- `SCHEMA_CARD` & `IdClass` definitions.
- The `classify()` and `normalise()` functions.
- The `allowlist` gate and `class_totality` logic.
- `withheld.jsonl` export and `sparse.py` (if determined unnecessary).

## 4. Build & Validation Order
1. **Schema & Indexing:** Add the text index alongside existing keys; verify parity via `lookup()`.
2. **Gateway Deletion:** Once the index is verified, remove the legacy allowlist gates.
3. **Tool Surface:** Implement MCP tools.
4. **Agent Integration:** Connect the agent to the MCP tool surface and validate the retrieval loop on the real corpus.

---
*This implementation roadmap replaces all previous pipeline logic. All new code will be strictly adhering to the "Verification by Construction" rule.*
