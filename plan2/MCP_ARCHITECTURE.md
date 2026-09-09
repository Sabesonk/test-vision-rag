# MCP Server Architecture: Vision Segmentation System

This document defines the MCP (Model Context Protocol) server structure for the Vision Segmentation system. The server acts as the centralized tool-provider for the agent, abstracting the Qdrant index, document storage, and VLM integration.

## 1. MCP Server Overview
- **Server Name:** `vision-segmentation-retriever`
- **Purpose:** Expose retrieval, reasoning, and verification tools to any MCP-compliant LLM client.
- **State Management:** The server maintains the `scope` (current context) as part of the session state.

## 2. MCP Tool Definitions

| MCP Tool | Description | Parameters |
| :--- | :--- | :--- |
| `skim_documents` | List binders/docs in scope | `query`, `scope`, `exclude` |
| `skim_sections` | List sections in a document | `query`, `scope`, `exclude` |
| `skim_pages` | List pages in a section | `query`, `scope`, `exclude` |
| `lookup` | Exact handle lookup | `label`, `scope`, `include_unverified` |
| `resolve` | Resolve printed labels to page_id | `printed_label`, `doc_id` |
| `fetch` | Get raw page image/text | `page_ids`, `dpi`, `region` |
| `read` | Delegate reasoning (Paid Step) | `page_ids`, `question` |
| `verify` | Structural claim verification | `claims`, `page_ids` |

## 3. Server Structure (Directory)

```text
mcp-server/
├── src/
│   ├── tools/          # Implementation of MCP tools
│   ├── indexer/        # Qdrant client & vector operations
│   ├── vlm/            # Gemini client & caching logic
│   └── state.py        # Session-based scope management
├── schema/             # JSON Schema for tool parameters
└── server.py           # MCP entry point (Stdio/SSE)
```

## 4. Key Implementation Logic

### Session State Management
The server must track the `scope` across multiple turns to support the "Zoom Ladder" without the agent having to pass the full context back every time.

```python
# Conceptual state management
class RetrievalState:
    def __init__(self):
        self.scope = {} # Stores current doc_id, section_id, etc.
        self.exclude_list = []
```

### Tool Invocation Pattern
All tools return consistent JSON responses that follow the "Disclosure Discipline":
- **Provenance:** Every result includes `page_id`, `run_id`, and `schema_version`.
- **Health:** Every result includes `grounded_rate` or `no_text` flags where applicable.

### Paid Step Protection
The `read()` tool will be wrapped in a mandatory cost-tracking decorator:
1. Check `page_ids` count against the 3-page limit.
2. Check `vlm_cache` (hash-based) to see if reasoning has already been performed.
3. Log the tool call to the audit trail for enterprise visibility.

## 5. Security & Observability
- **Auth:** MCP standard headers for identity propagation.
- **Logging:** All `read()` calls are logged with `(user_id, page_ids, timestamp, token_usage)`.
- **Error Handling:** Graceful handling of API rate limits (exponential backoff) and document unavailability (returning structured `not_found` or `not_searchable` states).
