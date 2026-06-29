# AIRA Master Architecture Codex

> Absolute source of truth for engineers and coding agents working on AIRA (Academic Integrity & Research Assistant).
>
> Last updated: 2026-06-29

## Core Directives for Future Agents

> Directive 1: Zero hallucination is mandatory. Never fabricate DOI, citation, retraction status, venue metadata, crawl records, or AI-detection evidence.
>
> Directive 2: Preserve contract truth over requested behavior. If code and docs diverge, update docs to match code and call out the divergence explicitly.
>
> Directive 3: Preserve structured payload compatibility. Frontend depends on `message_type` and `tool_results`, not on best-effort prose.
>
> Directive 4: Deterministic academic actions must stay deterministic. Explicit citation/retraction/grammar/AI-detection flows should not become ambiguous LLM-only behaviors.
>
> Directive 5: Do not weaken security defaults, ownership checks, or encryption boundaries for convenience.

---

## 1) System Overview

AIRA is a modular monolith for academic assistance.

- Frontend: Next.js 15 app with authenticated chat, verification mode, AI-rule management UI, and admin dashboard.
- Backend: FastAPI service exposing auth, sessions, chat, tool execution, AI-detection rule management, upload, manuscripts, journal match, venues, crawl-admin, and admin APIs.
- Data layer: SQLAlchemy models for chat, files, venue corpus, crawl state, manuscript assessment, and AI-detection rules.
- Academic engine: citation verification, retraction scanning, journal matching, AI-writing detection, grammar checking, and academic venue indexing.

Primary objective: provide grounded academic workflows with explainable evidence and minimal hallucination surface.

---

## 2) Tech Stack and External Integrations

### 2.1 Core Framework Stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | Next.js 15, React 18, TypeScript | App Router UI and client state |
| Backend API | FastAPI, Uvicorn | Routing, dependencies, lifecycle |
| Data layer | SQLAlchemy, Alembic | ORM and migrations |
| Settings | pydantic-settings | Environment-driven runtime configuration |

### 2.2 LLM and Reasoning Plane

| Component | Current implementation | Role |
|---|---|---|
| LLM provider | Groq SDK | Tool-calling chat runtime |
| Active model | `llama-3.1-8b-instant` | Default low-latency model |
| Reliability | tenacity + heuristic fallback | Recover from transient provider issues |
| Title generation | `generate_simple()` | Auto-title short session names |

Notes:

- Historical Gemini naming remains in some identifiers (`gemini_service`) but active execution path is Groq.
- The frontend never calls Groq directly; all reasoning stays behind backend routes.

### 2.3 Retrieval and Academic Data Plane

| Component | Implementation | Role |
|---|---|---|
| Vector/index store | ChromaDB | Persistent academic match/index storage |
| Embeddings | SPECTER2 | Academic retrieval embeddings |
| Crawl runtime | DrissionPage + source registry | Live academic source extraction |
| Venue enrichment | Clarivate/manual import + local SQL models | Venue metadata normalization |

### 2.4 Academic APIs and Tool Dependencies

| Domain | Libraries / APIs | Purpose |
|---|---|---|
| Citation integrity | Crossref, OpenAlex, DataCite, Semantic Scholar, optional Tavily | Verify references and enrich metadata |
| Retraction checks | Crossref, OpenAlex, PubPeer | Risk/retraction/community-signal scan |
| AI detection | transformers + torch + custom rule engine | AI-writing likelihood scoring |
| Grammar | LanguageTool | Grammar/spelling diagnostics |
| Storage | local filesystem / boto3 S3 | File persistence |

---

## 3) Repository Macro Modules

### 3.1 Frontend App Module

Path: `frontend/`

Responsibilities:

- route users through landing, login, chat, and admin UIs;
- persist auth state and chat state;
- render structured tool results via specialized cards;
- proxy same-origin `/api/v1/*` calls to the backend through Next.js rewrites.

Notable areas:

- `components/chat-view.tsx`
- `components/tool-results.tsx`
- `components/citation-report.tsx`
- `components/topbar.tsx`
- `components/ai-detect-rule-manager.tsx`
- `lib/api.ts`
- `lib/chat-store.tsx`

### 3.2 Backend API Module

Path: `backend/app/api/v1/`

Current router composition:

- `auth`
- `admin`
- `sessions`
- `chat`
- `tools`
- `ai_detection`
- `upload`
- `manuscripts`
- `journal_match`
- `venues`
- `crawl_admin`

Representative route surface:

- `/auth/*`
- `/sessions/*`
- `/chat/*`
- `/tools/*`
- `/ai-detection/*`
- `/upload/*`
- `/manuscripts/*`
- `/journal-match/*`
- `/venues/*`
- `/crawl/*`, `/crawl-admin/*`
- `/admin/*`

### 3.3 Core Platform Module

Path: `backend/app/core`

Responsibilities:

- settings and runtime safety validation;
- JWT and password security helpers;
- RBAC + ABAC authorization gateway;
- AES-GCM crypto and encrypted SQLAlchemy types;
- middleware for security headers and rate limiting;
- DB engine/session creation;
- audit logging.

### 3.4 Orchestration and Domain Services

Path: `backend/app/services`

Responsibilities:

- chat/session orchestration (`chat_service.py`);
- function-calling, pass-by-reference routing, and fallback (`llm_service.py`);
- upload/storage flows (`file_service.py`, `storage_service.py`);
- AI detection and rule compilation (`ai_detection_service.py`, `ai_detection_rule_service.py`);
- journal match domain (`journal_match/*`);
- ingestion/index services (`ingestion/*`, `embeddings/*`);
- external academic lookup helpers.

### 3.5 Academic Tools Module

Path: `backend/app/services/tools`

Tool surface:

- `citation_batch_service.py`
- `citation_checker.py`
- `citation/*`
- `retraction_scan.py`
- `ai_writing_detector.py`
- `grammar_checker.py`

Behavioral note:

- Citation verification now has a dedicated batch/report layer above the core verifier.
- Journal matching is no longer isolated to a single legacy tool file; it lives across `services/journal_match/*` and dedicated APIs.

### 3.6 Data Engineering / Crawl Module

Path: `backend/crawler`

Responsibilities:

- manage crawl source registry and connectors;
- collect raw academic source snapshots;
- normalize and dedupe data;
- rebuild academic index inputs and reindex flows;
- expose scheduler-backed admin operations.

---

## 4) Deep-Dive Mechanics

### 4.1 LLM Function Calling Loop (`backend/app/services/llm_service.py`)

Current verified mechanics:

1. Build system prompt + recent history + prepared user text.
2. Limit history to the last 4 messages and 2000 chars/message.
3. Truncate active router input to 10000 chars.
4. Convert long text or attached content into backend-side `document_id` references once input crosses 1500 chars or clearly represents a document.
5. Call Groq with dynamic tool list.
6. Resolve tool calls locally.
7. Early-exit terminal tools with structured payloads.
8. Stop after `_MAX_FC_ITERATIONS = 5`.

Important invariants:

- `detect_ai_writing` and `check_grammar` are document-only at the Groq-facing schema layer.
- `verify_citation`, `scan_retraction_and_pubpeer`, `match_journal` may use `document_id`.
- Out-of-scope `document_id` values must be rejected.
- Pseudo-tool text fragments must not leak into persisted assistant content as if they were valid tool calls.

### 4.2 Chat Orchestration (`backend/app/services/chat_service.py`)

Verified current behavior:

- Session titles default by mode, with `Trò chuyện mới` for `auto` and `general_qa`.
- Chat history is loaded before saving the current message to avoid duplicate-context bugs.
- Response payload includes updated serialized session so frontend can sync title/mode immediately.
- Auto mode can resolve into:
  - general academic QA,
  - citation verification,
  - retraction scan,
  - journal match,
  - grammar,
  - AI detection,
  - DOI metadata / academic lookup follow-up flows.

### 4.3 Citation Verification

Verified architecture:

- `citation_batch_service.verify_text()` is the report/batch entrypoint.
- `citation_checker.py` handles exact identifier and metadata match logic.
- `citation/*` submodules split parser, normalization, scoring, models, formatters, and source adapters.

Critical constraints:

- Exact DOI / identifier lookup must remain exact.
- No-DOI metadata matching can be strong, likely, possible, ambiguous, or unverified; it must not silently “upgrade” unsupported matches.
- Export metadata is only allowed when evidence supports it.
- Web fallback is bounded to citation verification; it is not general browsing.

### 4.4 Journal Match Domain

Verified architecture:

- Dedicated APIs: `/manuscripts/*`, `/journal-match/*`, `/venues/search`.
- Service decomposition: parser, retriever, reranker, filters, explainer, topic profile.
- Legacy `/tools/journal-match` still exists for chat compatibility.

Critical constraints:

- Do not collapse the dedicated domain back into a simplistic single-file matcher.
- Preserve separation between manuscript parsing, retrieval, reranking, and presentation payload shaping.

### 4.5 AI Detection and Grammar

Verified architecture:

- Phrase-rule preferences live on `/auth/me/ai-detection-rules`.
- Structured natural-language rule compilation and persistence live on `/ai-detection/rules*`.
- Direct analyze endpoint: `/ai-detection/analyze`.
- Grammar checking remains local-tool backed via LanguageTool.

Critical constraints:

- AI-detection output is probabilistic evidence, not definitive proof.
- Rule compilation errors and permission boundaries must stay explicit.
- Grammar auto-correction must remain conservative.

### 4.6 Crawl / Index Runtime

Verified architecture:

- Crawl jobs and reindex jobs are triggered via `/crawl/*` and `/crawl-admin/*`.
- Startup may bootstrap default sources and initialize collections depending on config.
- Academic ingest/index flows live across `crawler/*` and `services/ingestion/*`.

Critical constraints:

- No fabricated venue/crawl records on source failure.
- Degraded embedding/runtime states must log warnings clearly.

---

## 5) API and Security Contracts That Must Not Drift

### 5.1 Chat Contract

- Chat responses return `session_id`, `session`, `user_message`, and `assistant_message`.
- `assistant_message` semantics are driven by `message_type` + `tool_results`, not plain text alone.

### 5.2 Tool Result Contract

- Frontend cards depend on stable payload families such as:
  - `citation_report`
  - `journal_list`
  - `retraction_report`
  - `ai_writing_detection`
  - `grammar_report`
  - `file_upload`
  - `pdf_summary`
  - `multi_tool_report`
- Do not replace structured payloads with only untyped narrative text.

### 5.3 Auth / Authorization Contract

- Access control combines permission checks and ownership assertions.
- Admin-only APIs must stay behind `Permission.ADMIN_MANAGE`.
- Session, message, and file access must remain ownership-checked.

### 5.4 Storage / Crypto Contract

- Encrypted DB fields must stay encrypted by default.
- File download must always happen after access validation.
- Local and S3 storage backends must preserve the same security semantics from the caller’s perspective.

### 5.5 Frontend Transport Contract

- Frontend API calls are same-origin.
- `next.config.mjs` rewrites `/api/v1/*` and `/health`.
- Do not reintroduce frontend assumptions that the browser will call a separate backend origin directly unless the transport model is intentionally redesigned.

---

## 6) Source-of-Truth File Index

| Domain | Primary Files |
|---|---|
| Frontend shell | `frontend/app/*`, `frontend/components/*`, `frontend/lib/*` |
| App bootstrap | `backend/app/main.py` |
| API router | `backend/app/api/v1/router.py` |
| Endpoint surface | `backend/app/api/v1/endpoints/*.py` |
| Core security/config | `backend/app/core/*.py` |
| Chat orchestration | `backend/app/services/chat_service.py` |
| LLM orchestration | `backend/app/services/llm_service.py` |
| AI detection | `backend/app/services/ai_detection_service.py`, `backend/app/services/ai_detection_rule_service.py` |
| Citation tools | `backend/app/services/tools/citation_batch_service.py`, `backend/app/services/tools/citation_checker.py`, `backend/app/services/tools/citation/*` |
| Journal match | `backend/app/services/journal_match/*` |
| Ingestion/index | `backend/app/services/ingestion/*`, `backend/app/services/embeddings/*` |
| Crawl pipeline | `backend/crawler/*` |
| Migrations | `backend/alembic/*` |
| Security audit | `backend/security/pentest/*` |

---

## 7) Agent Handoff Checklist

Before changing architecture-sensitive code:

- Confirm behavior in code, not in legacy docs or issue descriptions.
- Preserve zero-hallucination constraints for academic outputs.
- Preserve `message_type` / `tool_results` contracts consumed by frontend renderers.
- Keep deterministic academic actions deterministic when intent is explicit.
- Validate permission and ownership boundaries on any new route or file flow.
- Update docs immediately when route composition, payload shape, or runtime behavior changes.
