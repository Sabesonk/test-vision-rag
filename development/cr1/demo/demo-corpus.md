# Demo corpus — the 40% slice

**Selected: 26 of 202 documents · 2,300 of 5,578 pages (41.2%) · 118 S2 windows · 144 API calls.**

Chosen for *coverage of the implementation*, not by counting files. Cost is not the binding
constraint (see below), so the slice is sized to exercise every code path and every evaluation set
in §6 rather than to save money.

## Cost — modelled on the as-built pipeline

| scope | today, batch | today, standard | 2027 standard |
|---|---:|---:|---:|
| **this 40% slice** | **$9.94** | $19.87 | $39.75 |
| the whole corpus | $23.88 | $47.77 | $95.53 |

Basis: `solution/Dataset Ingestion & Retrieval/effort_and_llm_cost_estimation.md` (Google pricing,
3 Sep 2026). Gemini 3.8 Flash $0.75/$3.75 per 1M through 31 Dec 2026, doubling 1 Jan 2027; Batch
API −50%. Image tokens 258 per 768px tile. Output 335 tok/page with the ×3 thinking allowance.

**Modelled, not measured.** `Cost.input_tokens` / `output_tokens` are declared on the run record
and never assigned — `vlm/client.py` reads `usage_metadata` and puts it on the log stream only, so
no run record carries real numbers. Every run in `vsir_runs` reads `input_tokens: 0`. Wire that up
and the first real run replaces this table with measurements.

## The slice

| pp | win | rung | document | why it is in |
|---:|---:|:--|---|---|
| 1440 | 69 | L1 | `AI Agent/Use & Maintenance/TC1AV8M2_1.0.pdf` | headline doc — alarm chapter (~494 records), component registers, bilingual, 69 windows |
| 592 | 20 | L1 | `AI Agent/Diagrams/ETC1AV81.PDF` | E/P/L sheets — identifier-dense; E carries the register / I-O / cable pages |
| 55 | 2 | L1 | `AI Agent/Use & Maintenance/Attachments/TC1E Schemi funzioni di sicurezza_1.3_Valido da Lotto 68_EN.pdf` | bilingual safety + lifting; carries the 2 scanned pages |
| 54 | 2 | L1 | `AI Agent/Diagrams/PTC1AV81.PDF` | E/P/L sheets — identifier-dense; E carries the register / I-O / cable pages |
| 34 | 2 | L1 | `AI Agent/Diagrams/LTC1AV81.PDF` | E/P/L sheets — identifier-dense; E carries the register / I-O / cable pages |
| 32 | 2 | L2 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/6449/20221111102138_l118_h3dk_solid-state_timers_datasheet_en.pdf` | Level 2 blind fold — no outline, >30pp (the fixes/001 path) |
| 31 | 2 | L1 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5124/20220621085106_6822945_EN.pdf` | Level 1 packed fold — dense outline coalesced up to the cap |
| 25 | 1 | L0 | `AI Agent/Use & Maintenance/Attachments/TC1E Verifiche periodiche su efficienza sistemi di sicurezza_1.1_EN.pdf` | bilingual safety + lifting; carries the 2 scanned pages |
| 6 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/379/20210412121148_TeSys D_LC1D25BL.pdf` | vendor datasheet, 3-6pp band |
| 5 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5309/20220713160933_MC.pdf` | zero text layer — proves not_searchable / no allowlist |
| 3 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/1592/20210823091710_6192049_EN.pdf` | vendor datasheet, 3-6pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5367/20220720151015_6202800_EN.pdf` | zero text layer — proves not_searchable / no allowlist |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/392/20210412130239_Datasheet_BES0068_265936_en.pdf` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/1453/20210818102302_Datasheet_BES00H4_235779_en.pdf` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/4042/20220405112529_wenglor_WM03PCT2.PDF` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5099/20220620153808_6150082_EN.pdf` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5325/20220714111956_6252166.pdf` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5378/20220720172019_19252datasheet.pdf` | vendor datasheet, 1-2pp band |
| 2 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/8091/20230322085600_f0e74a05f8d42bc22ac4cbcc58a1e17e.pdf` | vendor datasheet, 1-2pp band |
| 1 | 1 | L0 | `AI Agent/Use & Maintenance/Attachments/CE_TC1AV8_ITA-EN.pdf` | bilingual safety + lifting; carries the 2 scanned pages |
| 1 | 1 | L0 | `AI Agent/Use & Maintenance/Attachments/FOOD_COMPATIBILITY_TC1AV8.pdf` | bilingual safety + lifting; carries the 2 scanned pages |
| 1 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5296/20220712115440_LR_Instructions.pdf` | zero text layer — proves not_searchable / no allowlist |
| 1 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5374/20220720170354_3286410_Info_sheet_DE_EN.pdf` | zero text layer — proves not_searchable / no allowlist |
| 1 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/6056/20221018171733_DF-00515.pdf` | zero text layer — proves not_searchable / no allowlist |
| 1 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5201/20220628133853_156533datasheet.pdf` | vendor datasheet, 1-2pp band |
| 1 | 1 | L0 | `AI Agent/Datasheet/TC1AV8DS2_1.0/Datasheet/5218/20220630092512_526264datasheet.pdf` | vendor datasheet, 1-2pp band |

## What it exercises

- **all three ladder rungs** — 19 × L0, 6 × L1 (incl. the packed fold), 1 × L2 (blind fold, fixes/001)
- **all 7 zero-text documents** — `not_searchable`, the abstention path, no allowlist to check against
- **the 2 scanned attachment pages** — inside `TC1E Verifiche periodiche`
- **the §6 evaluation sets** — component register (E pp. 59–125), alarm catalogue (~494 records),
  cross-references — all inside the manual and `ETC1AV81`
- **the pilot** — `TC1E Schemi funzioni di sicurezza`, whose `expected.json` is normative
- **bilingual IT/EN** — manual + IMA attachments, so D5's per-language summaries are load-bearing
- **identifier-dense sheets** — E/P/L diagrams, where text extraction flattens to digit soup

## Running it

The manual is **310 MB**, over `MAX_UPLOAD_BYTES` (180 MiB), so it cannot go through
`POST /documents`. Use the CLI for that one, or raise the bound first.

Expect roughly 1.5–2.5 h interactive for 118 windows plus 2,300 page embeddings. The Batch API
halves the price and removes the latency constraint; §16 already says full-corpus runs go batch.
