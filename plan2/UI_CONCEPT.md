# Enterprise UI Concept: Vision Segmentation Retrieval

```mermaid
graph TD
    subgraph "Left Zone: Workspace (Document Viewer)"
        A[Zoom Ladder / Breadcrumbs] --> B[High-Res Document Viewer]
        B --> C[Interactive Bounding Boxes (Overlays)]
        C --> D[Region Zoom (DPI-Escalated)]
    end

    subgraph "Right Zone: Agentic Console"
        E[Collapsible Agent Moves (Skim/Read/Verify)] --> F[Evidence Triage Panel]
        F --> G[Draft Answer with Trust Badges]
        G --> H[Verification Highlight (Amber for warnings)]
    end

    subgraph "Cross-Zone Interactions"
        I[Click Part Code in Draft] -.-> C
        J[Hover Thumbnail] -.-> D
    end
```
