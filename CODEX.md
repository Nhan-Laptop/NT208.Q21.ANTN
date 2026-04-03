# AIRA Master Architecture Codex

> Absolute Source of Truth for AI agents and engineers working on AIRA (Academic Integrity & Research Assistant).
>
> Last updated: 2026-03-30

## Core Directives for Future Agents

> Directive 1: Zero hallucination is mandatory. Never fabricate DOI, citation, retraction status, journal metadata, or crawler outputs.
>
> Directive 2: Preserve offline safety behavior in the crawler and toolchain. If scraping fails, do not synthesize fake records.
>
> Directive 3: Respect API contracts exactly, especially the LLM handoff schema represented by FunctionCallingResponse (text, tool_calls, message_type, tool_results).
>
> Directive 4: Document and preserve real behavior over requested behavior. If code and docs diverge, docs must reflect code and explicitly note the divergence.

---

## 1) System Overview

AIRA is a full-stack academic integrity and research assistant platform.

- Backend: FastAPI service providing auth, chat, tool execution, file workflows, and admin endpoints.
- Frontend: Next.js 15 application for chat, session management, file upload, and admin monitoring.
- LLM orchestration: Groq chat-completions with OpenAI-compatible function calling.
- Academic tools: Citation verification, retraction scanning, journal matching, AI-writing detection, grammar checking.
- Data engineering pipeline: Config-driven crawler + embedding + ChromaDB persistent vector store.

Primary objective: deliver grounded, verifiable academic assistance with strict anti-hallucination constraints.

---

## 2) Tech Stack and External Integrations

### 2.1 Core Framework Stack

| Layer | Technology | Role |
|---|---|---|
| Backend API | FastAPI, Uvicorn | HTTP API, routing, dependency injection, app lifecycle |
| Data layer | SQLAlchemy | ORM for users, sessions, messages, file metadata |
| Settings | pydantic-settings | Environment-driven runtime configuration |
| Frontend | Next.js 15, React 18, TypeScript | Client UI and chat UX |

### 2.2 LLM and Reasoning Plane

| Component | Implementation | Role |
|---|---|---|
| LLM Provider | Groq SDK | Central reasoning and tool-routing engine |
| Active model | llama-3.1-8b-instant | Low-latency generation with tool calling |
| Call API | chat.completions.create | OpenAI-compatible function-calling loop |
| Reliability | tenacity retries + heuristic fallback | Recovers from transient provider failures |

Notes:
- Groq replaced Gemini as active runtime LLM service.
- Backward-compat aliases still exist in code (for example gemini_service variable names), but execution path is Groq.

### 2.3 Retrieval and Data Pipeline Stack

| Component | Implementation | Role |
|---|---|---|
| Vector DB | ChromaDB PersistentClient | Stores CFP vectors in local persistent collection |
| Collection | journal_cfps | Semantic retrieval target for journal matching |
| Embeddings | sentence-transformers allenai/specter2_base | Encodes crawler records and user query text with 768-dimensional academic-literature embeddings |
| Scraping transport | DrissionPage (CDP-based Chromium automation) | Renders dynamic publisher pages and survives modern WAF / anti-bot challenges |
| HTML parsing | DrissionPage DOM queries | Extracts live CSS-selected CFP metadata such as deadlines, scopes, and deep links |

Scope note:
- `allenai/specter2_base` is the active embedding model for ChromaDB ingestion/retrieval (`journal_cfps`).
- `all-MiniLM-L6-v2` is still used only by `heuristic_router.py` for fallback intent classification when Groq calls fail.

### 2.4 Academic APIs and Tool Dependencies

| Domain | Libraries / APIs | Purpose |
|---|---|---|
| Citation integrity | PyAlex, Habanero, httpx | Verify references against OpenAlex/Crossref |
| Retraction checks | OpenAlex, Crossref, PubPeer endpoint handling | Retraction/correction/concerning-paper analysis |
| AI detection | transformers + torch | RoBERTa-based AI-writing scoring |
| Grammar | language_tool_python | Grammar/spelling diagnostics |

### 2.5 Security and Platform Dependencies

| Concern | Implementation |
|---|---|
| Authentication | JWT (HS256) via python-jose |
| Password hashing | bcrypt |
| Encryption | PyCryptodome AES-GCM stack used by crypto layer |
| Middleware | Security headers + rate limiting middleware |

---

## 3) Repository Macro Modules

### 3.1 Backend API Module

Path: backend/app/api

Responsibilities:
- Hosts v1 router composition and endpoint modules.
- Exposes REST endpoints for auth, sessions, chat, tools, upload, and admin.
- Chat handlers are HTTP endpoints (no WebSocket handlers currently implemented in this module).

Route composition:
- backend/app/api/v1/router.py includes: auth, admin, sessions, chat, tools, upload.

Representative endpoint surface:
- /auth: register, login, me, admin/promote.
- /chat: completions, session-targeted completion, encrypted completion.
- /sessions: CRUD + message listing.
- /tools: verify-citation, journal-match, retraction-scan, summarize-pdf, detect-ai-writing, check-grammar.
- /upload: upload, list, stats, download/delete, presigned URLs.
- /admin: overview, user role management, file/storage management.

### 3.2 Core Platform Module

Path: backend/app/core

Responsibilities:
- settings and environment normalization.
- database session/engine wiring.
- cryptography and encrypted payload support.
- security primitives (password/JWT/current-user dependency).
- RBAC + ABAC authorization gateway.
- security headers and rate-limiter middleware.
- audit logging and limiter state management.

Key behavior highlights:
- Startup security validators reject insecure defaults outside development.
- JWT payload includes sub, exp, iat, and jti claims.
- Security and rate-limit middleware are globally attached in app startup.

### 3.3 Service Layer Module

Path: backend/app/services

Responsibilities:
- Business orchestration for sessions/messages/files.
- LLM orchestration and function-calling state machine.
- Bootstrap/admin creation on startup.
- Heuristic fallback routing when provider calls fail.
- Storage strategy abstraction.

Notable services:
- llm_service.py: Groq orchestration, strict function-calling loop, and lightweight auto-title generation for new chats.
- chat_service.py: mode routing, file-context injection, persistence of user/assistant messages.
- file_service.py and storage_service.py: file metadata and storage interactions.
- heuristic_router.py: semantic intent fallback when Groq is unavailable.

### 3.4 Academic Tools Module

Path: backend/app/services/tools

Responsibilities:
- Implements domain tools callable by LLM or direct tool endpoints.
- Exposes singleton instances for runtime use.

Tool set:
- citation_checker: reference extraction + verification pipeline.
- retraction_scan: DOI risk/retraction/concerning-paper checks.
- journal_finder: ChromaDB semantic match for journal CFP recommendations using Specter2 embeddings and bounded similarity scoring.
- ai_writing_detector: ML + rule-based AI text likelihood.
- grammar_checker: LanguageTool-based correction diagnostics.

### 3.5 Data Engineering Pipeline Module

Path: backend/crawler

Responsibilities:
- Crawl live CFP sources from configured publishers.
- Normalize records into deterministic format.
- Embed title/scope text with a 768-dimensional academic retrieval model.
- Rebuild and upsert ChromaDB collection used by Journal Finder.

Pipeline files:
- sources.json: source URLs and CSS selectors.
- universal_scraper.py: DrissionPage extraction executor for live CFP pages.
- db_builder.py: embedding + ChromaDB load.
- run.py: orchestration entrypoint.

---

## 4) Deep-Dive Mechanics

### 4.1 LLM Function Calling Loop (backend/app/services/llm_service.py)

Operational sequence:

1. Build message array:
- Add system prompt.
- Append conversation history.
- Replace attached/oversized raw document text with metadata-only references (`document_id`, text length) before sending the prompt to Groq.
- Append current user message.

2. Invoke Groq chat completions:
- model = settings.groq_model
- tools = _GROQ_TOOLS
- tool_choice = auto

3. If tool_calls are present:
- Parse each requested function name and JSON arguments.
- If a tool call contains `document_id`, resolve it back to the cached full text inside the backend execution layer.
- Dispatch to local Python callable via _TOOL_FUNCTIONS registry.
- Capture tool output.
- Append tool message back into conversation.
- Continue iterative loop.

4. If no tool_calls:
- Final synthesized assistant text is returned.
- If tool calls happened earlier, map first tool to message_type and build structured tool_results payload for frontend cards.

5. Loop safety:
- Max iterations capped by _MAX_FC_ITERATIONS = 5.

6. Fallback path on provider failure:
- _call_chat_completions is retried with tenacity.
- After retry failure, _try_heuristic_fallback attempts semantic intent routing + direct local tool execution.
- If heuristic routing cannot classify intent, return static overload/failure message.

### 4.1.1 Context Management and Token-Limit Protections

Router protections in `llm_service.py`:

- Sliding window: only the last 4 user/assistant history messages are sent to Groq.
- History truncation: each retained history message is capped at 2,000 characters and suffixed with `...[truncated]` when clipped.
- Current-input truncation: the active user payload is capped at 10,000 characters and tagged with a visible truncation notice.

Architectural purpose:

- Groq is treated primarily as a router/tool-caller, not as a long-context document processor.
- These limits protect the OpenAI-compatible Groq request body from 413 payload/rate-limit failures and 400 tool-use failures caused by oversized JSON arguments.
- The system preserves enough recent context for intent routing while preventing massive pasted text from destabilizing tool calling.

### 4.1.2 Auto-Title Generation

New-session UX behavior:

- When the first user message is sent in a session whose title is still the default placeholder, the backend issues a secondary lightweight `generate_simple()` call to produce a concise Vietnamese title.
- The title-generator prompt is constrained to return only a 4-5 word session summary with no explanation text.
- The generated title is committed back to the `chat_sessions.title` field before the chat response is returned.
- Chat completion responses now include the updated serialized session object so the frontend sidebar can sync the renamed session immediately without relying on raw first-message text.

### 4.1.3 Pass-by-Reference Document Routing

Enterprise routing mechanism:

- Raw attached documents and oversized pasted text are cached in-memory on the backend and assigned a stable `document_id`.
- Groq receives only metadata such as `document_id` and character length, never the full cached document body.
- Tool schemas expose `document_id` so the model can route intent using a reference instead of embedding large raw text into JSON arguments.
- `_execute_tool_call()` resolves `document_id` back to full text immediately before the local Python/ML tool runs, then strips the reference key from the callable arguments.
- Heuristic fallback can also reconstruct the cached document from `document_id`, so provider outages do not require the LLM to carry raw file text.

Architecture intent:

- This is a pass-by-reference design: Document Cache -> Groq receives only ID/metadata -> Groq returns tool call with ID -> Backend resolves ID to text -> ML tool executes.
- The goal is to permanently reduce Groq 413 payload/rate-limit failures and 400 malformed tool-call JSON failures caused by sending large raw document payloads through the OpenAI-compatible function-calling interface.

Strict response contract:

```python
@dataclass
class FunctionCallingResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    message_type: str
    tool_results: dict[str, Any] | None
```

### 4.2 Data Pipeline and Degradation Behavior (backend/crawler)

Execution flow:

1. run.py initializes UniversalScraper.
2. UniversalScraper loads sources.json.
3. For each publisher source:
- Open the live page with DrissionPage Chromium automation.
- Wait for dynamic content and anti-bot JavaScript challenges to settle.
- Extract title, deadline, scope, link, and publisher metadata from the rendered DOM using configured CSS selectors.

4. Aggregate all scraped records.
5. Always call seed_database(records):
- Delete existing journal_cfps collection (stale data purge).
- Recreate/get collection with cosine metric.
- Encode title + scope using allenai/specter2_base (768 dimensions).
- Upsert in batches.

Architecture note:
- The vector database now uses 768-dimensional embeddings tailored for academic literature via allenai/specter2_base, replacing the previous 384-dimensional all-MiniLM-L6-v2 general-purpose vectors.

Code-truth on fallback policy:
- Zero-hallucination behavior exists.
- If a source fails to load, is blocked by anti-bot defenses, or returns no parseable data, that source is skipped.
- If all sources fail, pipeline logs empty result and ChromaDB can be left empty.
- There is currently no seed_data.json fallback in backend/crawler.

Implication for future agents:
- Do not document or implement fake-data fallback.
- If introducing static fallback later, it must be real curated data and explicitly versioned.

### 4.3 Semantic Journal Matching (backend/app/services/tools/journal_finder.py)

Runtime mechanics:

1. Startup wiring:
- Connect to persistent ChromaDB directory at backend/data/chroma_db.
- Open collection journal_cfps if available.
- Load the fixed SentenceTransformer model allenai/specter2_base so query embeddings match the ingestion pipeline exactly.

2. Query flow on recommend(abstract, title, top_k):
- Build query text from title + abstract.
- Detect candidate topical domains from keyword heuristics.
- Query ChromaDB using allenai/specter2_base embeddings only.

3. Ranking logic:
- Normalize `None` metadata to `{}` before field access.
- Convert returned ChromaDB distance with `1.0 - dist`, clamp similarity into `[0.0, 1.0]`, apply domain-overlap bonus, then clamp again for a robust final score.
- Build response rows with journal title, score, rationale, URL, publisher, domains, deadline.
- Sort by score descending and return top_k.

Behavior under missing data:
- If collection is missing or empty, returns empty list rather than raising runtime failure.

---

## 5) API and Security Contracts That Must Not Drift

### 5.1 Chat Contract

- chat completion endpoints return session_id + serialized session + serialized user_message + assistant_message.
- assistant tool responses are encoded through message_type and tool_results payload.

### 5.2 Tool Invocation Contract

- Tool endpoints persist interaction into chat history through chat_service.persist_tool_interaction.
- Output shape must remain compatible with frontend tool result cards.

### 5.3 Auth/Security Contract

- JWT claims include sub, exp, iat, jti.
- Access control combines permission gates (RBAC) and ownership checks (ABAC).
- Middleware always enforces security headers and rate limiting unless explicitly disabled by settings.

Operational note:
- auth/login currently builds access token with explicit 24h timedelta in endpoint code, while settings default is 60 minutes. Treat as current behavior, and align deliberately in future changes.

---

## 6) Source-of-Truth File Index

| Domain | Primary Files |
|---|---|
| App bootstrap | backend/app/main.py |
| API router | backend/app/api/v1/router.py |
| Auth/session/chat endpoints | backend/app/api/v1/endpoints/*.py |
| Settings/security | backend/app/core/config.py, backend/app/core/security.py, backend/app/core/authorization.py |
| Middleware/rate limiting | backend/app/core/middleware.py, backend/app/core/rate_limit.py |
| LLM orchestration | backend/app/services/llm_service.py |
| Chat orchestration | backend/app/services/chat_service.py |
| Academic tools | backend/app/services/tools/*.py |
| Crawler and vector ingestion | backend/crawler/*.py, backend/crawler/sources.json |
| Embedding store | backend/data/chroma_db |

---

## 7) Agent Handoff Checklist

Before changing architecture-sensitive code:

- Confirm behavior in code, not in legacy docs.
- Preserve zero-hallucination constraints.
- Preserve function-calling data contracts.
- Validate fallback behavior under provider outage and crawler scrape failure.
- Keep tool payload formats backward compatible with frontend renderers.
