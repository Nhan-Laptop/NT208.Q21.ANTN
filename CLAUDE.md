# AIRA — Definitive System Context for AI Code-Generation Sessions

> **Purpose**: This file is the single source of truth that any AI assistant
> (Copilot, Cursor, Claude, Codex, etc.) should read **before** generating or
> modifying code in this repository. It captures the current architecture,
> conventions, key principles, and known constraints so that every future
> session starts with full context — zero ramp-up.
>
> **Last Updated**: Session 17 (documentation sync after Groq + ChromaDB migration)

---

## 1. Project Overview

| Field | Value |
|-------|-------|
| **Name** | AIRA — Academic Integrity & Research Assistant |
| **Purpose** | Web platform for scientific paper writing support. Integrates LLM chat (Groq), 5 specialist tools, a real-time journal CFP crawler, and a vector database. |
| **Repository root** | `/home/nhanlaptop/NT208/` |
| **Backend path** | `backend/` (FastAPI + Python 3.12) |
| **Frontend path** | `frontend/` (Next.js 15 + React 18 + TypeScript) |
| **Database** | SQLite (dev) / PostgreSQL (production) |
| **Vector DB** | ChromaDB — persistent at `backend/data/chroma_db/` |
| **Storage** | Local filesystem / AWS S3 (dual-backend via strategy pattern) |
| **Python venv** | `backend/.venv` — activate with `source backend/.venv/bin/activate` |

---

## 2. Technology Stack

### Backend
| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | FastAPI ≥ 0.115 + Uvicorn | Async ASGI |
| ORM | SQLAlchemy ≥ 2.0 | Declarative models, composite indexes |
| Validation | Pydantic v2 + pydantic-settings | `Settings` class in `core/config.py` |
| LLM | **Groq SDK** (`groq>=0.12.0`) | Model: `llama-3.1-8b-instant` via `chat.completions.create()` |
| Vector DB | **ChromaDB** (PersistentClient) | Collection `journal_cfps`, cosine HNSW, `all-MiniLM-L6-v2` embeddings |
| Crawler | cloudscraper + BeautifulSoup | `backend/crawler/`, config-driven via `sources.json` |
| ML — Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim) | Used by both ChromaDB pipeline and `SemanticIntentRouter` |
| ML — AI Detection | `transformers` (`roberta-base-openai-detector`) | RoBERTa ensemble (70% ML / 30% rule-based) |
| ML — Grammar | `language_tool_python` (JVM-based LanguageTool) | Lazy singleton, thread-safe |
| Auth | JWT HS256 via `python-jose` + bcrypt | 1h TTL, `iat`/`jti`/`sub`/`exp` claims |
| Encryption | AES-256-GCM via PyCryptodome | At-rest file encryption + `EncryptedText`/`EncryptedJSON` column types |
| HTTP Client | httpx with `HTTPTransport(retries=2)` | For Crossref, OpenAlex, PubPeer external calls |
| Academic APIs | PyAlex (OpenAlex), Habanero (Crossref), httpx (PubPeer) | PubPeer API is dead — handler degrades gracefully |
| Resilience | Tenacity (retry) + `HeuristicFallbackEngine` | 3-tier: Groq → Heuristic Router → Static fallback |

### Frontend
| Layer | Technology |
|-------|-----------|
| Framework | Next.js 15 (App Router) |
| UI | React 18 + Tailwind CSS v4 |
| State | `useReducer` chat store + React Query (admin) |
| Notifications | Sonner toast |
| Icons | Lucide React |
| Theme | Dark / Light via `ThemeProvider` + system preference |

### Data Engineering Pipeline (`backend/crawler/`)
| Component | File | Description |
|-----------|------|-------------|
| Config | `sources.json` | 3 publishers (Elsevier, MDPI, IEEE) with CSS selectors |
| Scraper | `universal_scraper.py` | `UniversalScraper` — cloudscraper with anti-bot bypass, polite delay |
| DB Builder | `db_builder.py` | Encodes CFPs via `all-MiniLM-L6-v2` → upserts into ChromaDB (MD5 hash IDs) |
| Runner | `run.py` | CLI: `cd backend && python -m crawler.run` |

---

## 3. Project Status (Post-Session 17)

| Component | Status | Notes |
|-----------|--------|-------|
| Backend (FastAPI) | ✅ Complete | 32+ modules, clean startup |
| Frontend (Next.js) | ✅ Complete | 0 build errors, 7 routes compiled |
| Database (SQLite) | ✅ Complete | Composite indexes added |
| Auth (JWT + RBAC) | ✅ Hardened | iat/jti claims, 1h TTL, startup validation |
| Chat System | ✅ Complete | Auto-session, mode routing, file context, rich tool cards |
| File Upload | ✅ Complete | AES-256-GCM encrypted at-rest |
| LLM (Groq) | ✅ Live | `llama-3.1-8b-instant`, 5 tools via function calling |
| Vector DB (ChromaDB) | ✅ Live | `journal_cfps` collection, cosine HNSW, MiniLM-L6-v2 |
| Crawler Pipeline | ✅ Live | 3 publishers (Elsevier, MDPI, IEEE) via cloudscraper |
| ML — AI Detection | ✅ Verified | RoBERTa ensemble (70/30), 4.8s inference |
| ML — Embeddings | ✅ Verified | `all-MiniLM-L6-v2` (384-dim) for ChromaDB + SemanticIntentRouter |
| ML — Grammar | ✅ Verified | LanguageTool (JVM), lazy singleton |
| External APIs | ✅ Audited | OpenAlex, Crossref, Habanero, PyAlex healthy; PubPeer dead → handled |
| Security Audit | ✅ Complete | 38 issues found → 28+ fixed |
| Rate Limiting | ✅ Hardened | Fixed X-Forwarded-For trust, memory cleanup |
| Tool Schemas | ✅ Fixed | Full data passthrough (was silently dropping fields) |
| Offline Fallback | ✅ Added | Model loading with `local_files_only=True` retry |
| Dark Mode | ✅ Complete | ThemeProvider + system preference |

---

## 4. Core Architecture

### 4.1 LLM Service (`llm_service.py` — ~859 LOC)

**Engine**: Groq SDK → `chat.completions.create()` with `tool_choice="auto"`

**5 Registered Tools** (`_GROQ_TOOLS`):

| Tool Name | Description | Backend Module |
|-----------|-------------|----------------|
| `scan_retraction_and_pubpeer` | Check retraction/correction status via DOI | `retraction_scan.py` |
| `verify_citation` | Verify citations against OpenAlex + Crossref | `citation_checker.py` |
| `match_journal` | Find matching journals from ChromaDB vector DB | `journal_finder.py` |
| `detect_ai_writing` | RoBERTa ensemble AI-text detection | `ai_writing_detector.py` |
| `check_grammar` | LanguageTool grammar/spelling check | `grammar_checker.py` |

**Function Calling Loop**: Sequential tool-message loop, max 5 iterations per turn. Each iteration: send messages → check `tool_calls` in response → execute tools → append tool results → re-send.

**SYSTEM_PROMPT** (Vietnamese, ~150 lines):
- **Core Mandate #1**: Zero hallucination — never fabricate DOI, citations, journal names, retraction status, PubPeer data
- **Core Mandate #2**: Always call tools for academic queries; never answer from "memory" alone
- **Core Mandate #3**: If tool unavailable, respond with knowledge but flag: "⚠️ Thông tin này dựa trên kiến thức chung, chưa được xác minh bằng hệ thống."
- **File Workflow**: Auto-extract DOI/References from attached PDFs; never ask user to copy/paste
- **Tone**: Direct, brief, academic Vietnamese. Keep technical terms in English.

**3-Tier Resilience**:
1. **Groq API** (primary) — Tenacity retry with exponential backoff on `APIStatusError` / `APIConnectionError`
2. **Heuristic Fallback** (`heuristic_router.py`) — `fallback_process_request()`: extract DOIs/abstract → `SemanticIntentRouter` (all-MiniLM-L6-v2, cosine ≥ 0.35) determines intent → directly execute tool → template response
3. **Static fallback** — "AI quá tải" message if both tiers fail

### 4.2 Heuristic Fallback Router (`heuristic_router.py`)

**Purpose**: Process tool requests WITHOUT Groq when API is unavailable (503/429/quota exhausted).

**3-Layer Intent Detection**:
1. **Smart defaults** — DOI present → RETRACTION; long text → AI_DETECT or GRAMMAR
2. **Semantic routing** — `SemanticIntentRouter` singleton (all-MiniLM-L6-v2, 384-dim) encodes user query → cosine similarity against 5 pre-computed intent embeddings
3. **Keyword fallback** — exact substring matching (safety net)

**5 Intents**: RETRACTION, CITATION, JOURNAL, AI_DETECT, GRAMMAR

### 4.3 Tool Details

**JournalFinder** (`journal_finder.py`):
- Primary: Query ChromaDB (`backend/data/chroma_db/`, collection `journal_cfps`) with SentenceTransformer-embedded abstracts
- Fallback: TF-IDF cosine similarity (no ML) if ChromaDB empty or unavailable
- ML model candidates: `specter2_base` → `scibert` → `MiniLM-L6-v2` → TF-IDF
- Offline support: `local_files_only=True` retry for cached models
- Domain detection: 10 domain categories via keyword matching + bonus scoring

**CitationChecker** (`citation_checker.py`):
- 6 citation patterns: APA inline/reference, IEEE numbered, Vancouver, DOI regex, simple author-year
- Verification chain: PyAlex (OpenAlex) → Habanero (Crossref) → httpx direct fallback
- Fuzzy matching via `SequenceMatcher` with confidence scoring (year + author match)

**RetractionScanner** (`retraction_scan.py`):
- Sources: Crossref `update-to` field + OpenAlex `is_retracted` + PubPeer API (dead → manual search URL)
- Title-based detection: "RETRACTED:" prefix check (mitigates unreliable Crossref field)
- Risk levels: NONE / LOW / MEDIUM / HIGH / CRITICAL with multi-factor assessment

**AIWritingDetector** (`ai_writing_detector.py`):
- Ensemble: RoBERTa `roberta-base-openai-detector` (70% weight) + rule-based heuristics (30%)
- 25 AI patterns + transition phrases + filler phrases
- Metrics: TTR, hapax ratio, sentence length uniformity
- Verdicts: LIKELY_HUMAN / POSSIBLY_HUMAN / UNCERTAIN / POSSIBLY_AI / LIKELY_AI

**GrammarChecker** (`grammar_checker.py`):
- Wraps `language_tool_python` (JVM-based LanguageTool)
- Lazy singleton, thread-safe via `threading.Lock()`
- Returns: total_errors, issues (rule_id, message, offset, length, replacements, category), corrected_text

### 4.4 Data Engineering Pipeline

```
sources.json (3 publishers: Elsevier, MDPI, IEEE)
    │
    ▼
UniversalScraper (cloudscraper + BeautifulSoup)
    │  ─ CSS-selector-driven extraction
    │  ─ Polite delay: random 1.0–2.5s between publishers
    │  ─ Zero hallucination: skip blocked publishers, never inject fake data
    │
    ▼
db_builder.py (SentenceTransformer: all-MiniLM-L6-v2)
    │  ─ Encode CFP titles + scopes → 384-dim vectors
    │  ─ Deterministic IDs via MD5 hash of URL/title
    │  ─ Batch upsert (max 5000 per batch)
    │
    ▼
ChromaDB PersistentClient
    ─ Path: backend/data/chroma_db/
    ─ Collection: journal_cfps
    ─ Distance: cosine (HNSW space)
```

**Run**: `cd backend && python -m crawler.run`

### 4.5 Chat Service (`chat_service.py`)

- `complete_chat()`: main chat loop — mode-specific tool routing OR general Q&A via LLM
- Mode routing: `VERIFICATION` → citation_checker, `JOURNAL_MATCH` → journal_finder, `RETRACTION` → retraction_scanner, `AI_DETECTION` → ai_writing_detector
- File context: extracts latest PDF text (max 15,000 chars) and injects into user message as XML block
- Session title auto-derive: first 8 words of first message
- Context window: last 8 messages (configurable via `chat_context_window`)

---

## 5. Configuration (`core/config.py`)

Key settings (via `.env` / pydantic-settings):

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `groq_api_key` | `str \| None` | `None` | **Active LLM key** |
| `groq_model` | `str` | `"llama-3.1-8b-instant"` | Active model |
| `google_api_key` | `str \| None` | `None` | Backward-compatible (unused by active LLM) |
| `gemini_model` | `str` | `"gemini-flash-latest"` | Backward-compatible (unused) |
| `hf_token` | `str \| None` | `None` | HuggingFace token for gated models |
| `jwt_secret_key` | `str` | `"replace-me-in-production"` | Blocked in non-dev if unchanged |
| `access_token_expire_minutes` | `int` | `60` | 1 hour |
| `chat_context_window` | `int` | `8` | Messages in LLM context |
| `max_upload_size_mb` | `int` | `20` | File upload limit |
| `database_url` | `str` | `"sqlite:///./aira.db"` | SQLite dev / PostgreSQL prod |

**Validators**: `@model_validator` blocks startup in non-dev with insecure JWT_SECRET_KEY or ADMIN_PASSWORD. Empty strings normalized to `None` for API keys.

---

## 6. Security Architecture

### Authentication Flow
```
User → POST /auth/login (email+password)
     → bcrypt.checkpw() → create_access_token(sub=user_id, iat, jti, exp=1h)
     → JWT stored in localStorage → sent as Bearer token
     → get_current_user() → decode JWT → query User → inject into endpoint
```

### Authorization Model (RBAC + ABAC)
```
Roles:           ADMIN → all 6 permissions
                 RESEARCHER → 5 permissions (no admin:manage)

Permissions:     session:read, session:write, message:write,
                 tool:execute, file:upload, admin:manage

ABAC:            assert_session_access() → ownership check + admin bypass
                 assert_message_access() → via session ownership
                 assert_file_access()    → user_id match + admin bypass
```

### Encryption Layers
```
Layer 1 (Transit):  HTTPS + CSP + HSTS headers
Layer 2 (JWT):      HS256 signed tokens with iat/jti/exp claims
Layer 3 (At-Rest):  AES-256-GCM via EncryptedText/EncryptedJSON SQLAlchemy types
Layer 4 (Files):    AES-256-GCM file encryption in StorageService
Layer 5 (Optional): Client-side encrypted chat payloads (EncryptedPayload schema)
```

### Middleware
- `SecurityHeadersMiddleware`: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP, HSTS
- `RateLimitMiddleware`: per-endpoint rate limits (auth: 10/min, chat: 60/min, tools: 40/min, upload: 20/min)

---

## 7. File Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, shutdown hooks
│   ├── core/
│   │   ├── config.py              # Settings, @model_validator, rate limit config
│   │   ├── security.py            # JWT HS256 (iat/jti/sub/exp), bcrypt, OAuth2
│   │   ├── authorization.py       # RBAC + ABAC gateway
│   │   ├── crypto.py              # AES-256-GCM CryptoManager
│   │   ├── encrypted_types.py     # SQLAlchemy EncryptedText/EncryptedJSON
│   │   ├── database.py            # SQLAlchemy engine + session
│   │   ├── middleware.py          # SecurityHeaders + RateLimit middlewares
│   │   ├── rate_limit.py          # Per-endpoint limits, periodic cleanup
│   │   └── audit.py               # Audit event logger
│   ├── models/
│   │   ├── user.py                # User model (role, hashed_password)
│   │   ├── chat_session.py        # ChatSession (title, mode)
│   │   ├── chat_message.py        # ChatMessage (role, message_type, tool_results)
│   │   └── file_attachment.py     # FileAttachment (encrypted, storage_key)
│   ├── schemas/
│   │   ├── auth.py                # UserCreate, UserOut, Token
│   │   ├── chat.py                # ChatRequest, ChatResponse
│   │   ├── admin.py               # AdminUserOut, AdminOverview
│   │   ├── tools.py               # CitationItem, JournalItem, RetractionItem
│   │   └── upload.py              # FileUploadResponse (no storage_key leak)
│   ├── api/v1/
│   │   ├── router.py              # Central router (6 endpoint modules)
│   │   └── endpoints/
│   │       ├── auth.py            # register/login/me/promote
│   │       ├── sessions.py        # CRUD + pagination
│   │       ├── chat.py            # complete_chat endpoint
│   │       ├── tools.py           # 6 tool endpoints (direct access)
│   │       ├── upload.py          # File upload/download/list
│   │       └── admin.py           # Admin dashboard + user management
│   └── services/
│       ├── bootstrap.py           # Safe admin creation (blocks defaults in non-dev)
│       ├── chat_service.py        # ChatService — mode routing, file context, LLM call
│       ├── file_service.py        # FileService — SQL aggregation, pagination
│       ├── llm_service.py         # Groq SDK, 5 tools, FC loop, 3-tier resilience
│       ├── heuristic_router.py    # SemanticIntentRouter + keyword fallback
│       ├── storage_service.py     # S3/Local dual-backend + AES encryption
│       └── tools/
│           ├── __init__.py        # Exports 5 classes + 5 singletons
│           ├── journal_finder.py  # ChromaDB + SentenceTransformer, TF-IDF fallback
│           ├── citation_checker.py # PyAlex + Habanero + httpx, 6 formats
│           ├── retraction_scan.py # Crossref + OpenAlex + PubPeer (dead→graceful)
│           ├── ai_writing_detector.py # RoBERTa ensemble (70/30)
│           └── grammar_checker.py # LanguageTool JVM wrapper
├── crawler/
│   ├── sources.json               # 3 publishers with CSS selectors
│   ├── universal_scraper.py       # cloudscraper + BeautifulSoup
│   ├── db_builder.py              # MiniLM-L6-v2 → ChromaDB upsert
│   └── run.py                     # CLI: python -m crawler.run
├── data/
│   └── chroma_db/                 # ChromaDB persistent storage
├── requirements.txt
├── scripts/generate_keys.py
└── security/pentest/

frontend/
├── app/
│   ├── globals.css                # Tailwind v4 @theme with color tokens
│   ├── layout.tsx                 # Hydration fix, Inter font
│   ├── providers.tsx              # ThemeProvider + Sonner Toaster
│   ├── page.tsx                   # Landing page
│   ├── login/page.tsx             # Login/Register form
│   ├── admin/page.tsx             # Admin dashboard (React Query)
│   └── chat/
│       ├── layout.tsx             # ChatProvider + Sidebar
│       ├── page.tsx               # ChatView renderer
│       └── [sessionId]/page.tsx   # Session-specific chat
├── components/
│   ├── auth-guard.tsx             # Auth + admin guard HOC
│   ├── chat-shell.tsx             # Sidebar (sessions, theme, user)
│   ├── chat-view.tsx              # React.memo, tool render, hooks
│   ├── tool-results.tsx           # 6 rich tool result card components
│   └── topbar.tsx                 # ModeSelector dropdown
├── hooks/
│   ├── useAutoScroll.ts           # Smart scroll on new messages only
│   └── useFileUpload.ts           # Drag-and-drop + progress tracking
├── lib/
│   ├── api.ts                     # 25 API methods + error handling
│   ├── auth.tsx                   # AuthProvider, registerAndLogin
│   ├── chat-store.tsx             # useReducer ChatStore
│   ├── theme.tsx                  # ThemeProvider (dark/light)
│   └── types.ts                   # 10 TypeScript interfaces
├── package.json
├── postcss.config.mjs
├── next.config.mjs
└── tsconfig.json
```

---

## 8. Key Principles

### Zero Hallucination Policy
- **Scraper**: Never inject fake CFP data. If publisher blocks request → skip entirely, return `[]`
- **LLM**: SYSTEM_PROMPT mandates: never fabricate DOIs, citations, journal names, retraction status
- **Tools**: All academic data from live API calls (OpenAlex, Crossref). No hardcoded mock data.
- **No `seed_data.json`**: Does not exist. Crawler returns real data only.

### Graceful Degradation
- **LLM unavailable** → HeuristicFallbackEngine → static message
- **ML model unavailable** → TF-IDF fallback (journal_finder), rule-based only (ai_detector)
- **External API down** → httpx retries (2x), then partial results + warning
- **PubPeer dead** → `pubpeer_comments=0` + manual search URL
- **Java not installed** → grammar_checker returns unavailable gracefully

### Configuration-Driven
- **Crawler**: `sources.json` defines publishers + CSS selectors (add new publishers without code changes)
- **Rate limits**: All configurable via `.env` (per-endpoint)
- **CORS**: Comma-separated origins in `.env`
- **Storage**: Strategy pattern — switch S3/Local via config

---

## 9. Dependencies

### Backend (`requirements.txt`)
```
fastapi>=0.115.0, uvicorn, sqlalchemy>=2.0.30, pydantic-settings>=2.4.0
python-jose[cryptography], bcrypt, pycryptodome
groq>=0.12.0, httpx, python-dotenv
boto3, PyMuPDF, language-tool-python
cloudscraper, beautifulsoup4, chromadb
numpy, scikit-learn, pyalex, habanero
sentence-transformers, transformers, torch
```

### Frontend (`package.json`)
```
next ^15.0.4, react ^18.3.1, tailwindcss ^4.1.18
@tanstack/react-query ^5.62.9, sonner ^2.0.7
lucide-react ^0.564.0, clsx ^2.1.1
```

---

## 10. Session History (Cumulative)

### Sessions 1–5: Foundation
- **S1**: Backend CRUD + Storage + Frontend UI rewrite + Phase 1–5
- **S2**: V2→V1 merge (deleted 4 `*_v2.py`), ML package installation, all tools verified
- **S3**: Security audit (38 issues, 28+ fixed: JWT hardening, rate limit, indexes, pagination, info leaks)
- **S4**: LLM migration from deprecated `google.generativeai` → `google-genai` SDK, SPECTER2 fix, frontend tool-results components
- **S5**: Runtime bugs (EmailStr, hf_token), PubPeer dead API, title-based retraction, schema data loss, offline model fallback, report.md expansion

### Sessions 14–16: Groq + ChromaDB Migration
- **S14**: Full LLM migration from Google Gemini → **Groq SDK** (`llama-3.1-8b-instant`), rewrote `llm_service.py` with OpenAI-compatible function calling, 5 tools with JSON parameter schemas, Tenacity retry + `HeuristicFallbackEngine` 3-tier resilience
- **S15**: **ChromaDB vector database** replacing hardcoded JournalFinder. Built `backend/crawler/` pipeline: `sources.json` config → `UniversalScraper` (cloudscraper) → `db_builder.py` (SentenceTransformer + ChromaDB). Rewrote `journal_finder.py` to query ChromaDB with TF-IDF fallback.
- **S16**: cloudscraper upgrade with zero-hallucination policy enforcement. No mock data, no `seed_data.json`.

### Session 17: Documentation Sync
- Updated `architecture.md` (~100+ replacements: all Gemini→Groq, SPECTER2→ChromaDB, 20+ Mermaid diagrams rewritten)
- Updated `README.md` (badges, features, tech stack, env vars, project structure, roadmap)
- Rewrote `CLAUDE.md` (this file) as definitive AI system context

---

## 11. TODO

### ✅ Completed
- [x] Backend Phase 1–5: Core infrastructure, tools, security
- [x] Frontend: UI/UX overhaul, tool cards, hooks
- [x] Groq LLM migration (Session 14)
- [x] ChromaDB + crawler pipeline (Session 15)
- [x] Zero-hallucination scraper policy (Session 16)
- [x] Documentation sync — architecture.md, README.md, CLAUDE.md (Session 17)

### 🔴 High Priority
- [ ] Alembic database migrations
- [ ] Token revocation (Redis blacklist)
- [ ] Async refactor (sync endpoints block event loop)
- [ ] Unit tests for backend + frontend

### 🟡 Medium Priority
- [ ] Redis cache, WebSocket chat, StreamingResponse
- [ ] httpOnly cookie auth, client-side token expiry
- [ ] Mobile responsive sidebar

### 🟢 Low Priority
- [ ] E2E tests, i18n, Email notifications

---

## 12. Known Issues

1. **RoBERTa Limitation**: Trained on GPT-2 → may underrate modern AI text (ChatGPT, Claude)
2. **SQLite limitations**: No concurrent writes, no ALTER TABLE migration
3. **S3 `get_stats()`**: Not scalable for large buckets (lists all objects)
4. **PubPeer API Dead**: All endpoints return 404 HTML — handler degrades to `pubpeer_comments=0` + manual search URL
5. **Crossref `update-to` Unreliable**: Empty for many retracted papers — mitigated by title-based "RETRACTED:" prefix + OpenAlex `is_retracted`
6. **Token storage**: `localStorage` (XSS vector; needs httpOnly cookies)
7. **No Alembic migrations**: Production risk
8. **`config.py` backward-compat fields**: `google_api_key` and `gemini_model` still exist but are unused by active LLM (Groq). Safe to remove when migration fully confirmed.
