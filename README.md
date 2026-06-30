<p align="center">
  <img src="https://img.shields.io/badge/AIRA-Academic%20Integrity%20%26%20Research%20Assistant-blue?style=for-the-badge&logo=bookstack&logoColor=white" alt="AIRA Badge"/>
</p>

<h1 align="center">🎓 AIRA — Academic Integrity & Research Assistant</h1>

<p align="center">
  <strong>Unified academic research workspace with chat, citation verification, journal matching, retraction scanning, AI-writing detection, grammar review, and encrypted file workflows.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Next.js_15-000000?style=flat-square&logo=next.js&logoColor=white" alt="Next.js"/>
  <img src="https://img.shields.io/badge/React_18-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React"/>
  <img src="https://img.shields.io/badge/Tailwind_CSS_v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind"/>
  <img src="https://img.shields.io/badge/Groq-LLaMA_3.1-F55036?style=flat-square&logo=meta&logoColor=white" alt="Groq"/>
  <img src="https://img.shields.io/badge/ChromaDB-4A154B?style=flat-square&logo=databricks&logoColor=white" alt="ChromaDB"/>
  <img src="https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript"/>
</p>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Prerequisites](#-prerequisites)
- [Installation & Local Setup](#-installation--local-setup)
- [Environment Variables](#-environment-variables)
- [Running the Application](#-running-the-application)
- [Temporary Public Demo with ngrok](#-temporary-public-demo-with-ngrok)
- [Project Structure](#-project-structure)
- [API Endpoints](#-api-endpoints)
- [ML Models & AI Pipeline](#-ml-models--ai-pipeline)
- [Security Architecture](#-security-architecture)
- [Documentation](#-documentation)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 🌟 Overview

**AIRA** is a full-stack academic assistant focused on grounded, source-backed research workflows. The current project combines:

- conversational chat with deterministic academic-tool routing,
- citation verification for single references or whole bibliographies,
- journal / venue matching backed by a local academic index,
- retraction scanning,
- AI-writing detection with user and structured custom rules,
- grammar checking,
- encrypted upload and manuscript parsing,
- admin monitoring and crawl / reindex operations.

Snapshot in this README was verified against the repository on **2026-06-29**.

### 🎯 What Problem It Solves

- Researchers typically switch between multiple disconnected services for reference checking, venue selection, AI-writing review, grammar review, and manuscript handling.
- Generic chat tools are weak at preserving academic evidence and often over-claim.
- File, chat, and metadata workflows need consistent access control and encryption in one system.

### 💡 Current Project Direction

AIRA is now closer to a modular academic workspace than a simple chat UI. In addition to the legacy `/tools/*` endpoints used by chat, the backend also exposes dedicated APIs for:

- AI detection rule compilation and management,
- manuscript upload and parse flows,
- journal-match request/result workflows,
- venue search,
- crawl run / reindex admin operations.

---

## ✨ Key Features

| Feature | Current Behavior | Powered By |
|---------|------------------|------------|
| 💬 **Academic Chat** | Session-based chat with `auto`, `general_qa`, `verification`, `journal_match`, `retraction`, `ai_detection` modes. Auto mode can route to deterministic tool execution when intent is explicit. | FastAPI + Groq |
| 📝 **Citation Verification** | Batch verification for pasted bibliographies plus legacy single-text endpoint. Supports exact **DOI, PMID, PMCID, OpenAlex ID** lookup and no-DOI metadata matching with field-level evidence. | Crossref + OpenAlex + DataCite + Semantic Scholar + optional Tavily fallback |
| 📚 **Journal Matching** | Dedicated journal-match pipeline built around parsed manuscript data, local academic venue records, topic profiling, reranking, and legacy chat-compatible journal cards. | ChromaDB + SPECTER2 |
| 🔍 **Retraction Scanning** | DOI-focused retraction and risk scan with structured report output; no-DOI cases remain explicit instead of fabricated. | Crossref + OpenAlex + PubPeer |
| 🤖 **AI Writing Detection** | Ensemble scoring with ML + rule-based evidence, plus per-user phrase rules and structured custom rule compilation. | RoBERTa + custom rule engine + Groq for rule compilation |
| ✍️ **Grammar Review** | Offline grammar/spell checking with conservative correction behavior. Risky replacements are reported, not blindly auto-applied. | LanguageTool |
| 📄 **File & Manuscript Flow** | Encrypted upload, PDF text extraction, file-backed chat context, manuscript upload/parse, and download/delete workflows. | PyMuPDF + encrypted storage |
| 🧠 **Academic Data Pipeline** | Crawl, normalize, ingest, and reindex academic venue data for retrieval and journal match. | DrissionPage + SQLAlchemy + ChromaDB |
| 🔐 **Security Controls** | JWT auth, RBAC + ABAC checks, encrypted DB/file fields, security headers, rate limits, audit events. | python-jose + PyCryptodome + custom middleware |
| 👤 **Admin Operations** | Overview dashboard, user role management, file/storage inspection, crawl/reindex endpoints. | React Query + FastAPI admin APIs |

### Citation Verification Notes

- Exact identifiers stay exact. Unresolved DOI or identifier is reported as not found; it is not silently fuzzied into a different record.
- No-DOI references are matched through scholarly-source search and field scoring.
- Export fields such as `formatted_apa`, `formatted_bibtex`, and `csl_json` are only exposed when candidate evidence is strong enough.
- Web search, when enabled, is a constrained backend fallback for citation verification only. It is not a general browser tool.

---

## 🏛️ System Architecture

AIRA currently follows a **modular monolith** with layered services:

```text
Browser
  -> Next.js 15 frontend
  -> same-origin /api/v1 proxy rewrites
  -> FastAPI backend
     -> auth / sessions / chat / tools / ai-detection / upload
     -> manuscripts / journal-match / venues / crawl-admin / admin
     -> service layer and academic tool layer
     -> SQLAlchemy + encrypted fields + storage abstraction
     -> local academic index + ChromaDB + crawl/ingest pipeline
```

### Current High-Level Request Flow

```text
User action
  -> frontend state + typed API client
  -> backend permission checks
  -> chat orchestration or direct tool endpoint
  -> scholarly APIs / local models / local index
  -> structured payload persisted to chat history
  -> frontend tool card renderer
```

### Important Runtime Behaviors

- Frontend uses same-origin requests and proxies `/api/v1/*` through Next.js rewrites.
- Chat sessions default to `Trò chuyện mới`; backend can rename the session after the first message and returns the updated session object immediately.
- Large text / attached-document tool flows use backend-side document references instead of pushing raw file bodies through model tool arguments.
- Terminal tool results such as AI detection and grammar review return structured payloads for UI cards, not just plain assistant prose.

For more detail, see [`architecture.md`](./architecture.md), [`frontend.md`](./frontend.md), and [`module_tree.md`](./module_tree.md).

---

## 🛠️ Tech Stack

### Backend

| Technology | Purpose |
|------------|---------|
| **Python 3.12** | Main backend runtime |
| **FastAPI** | HTTP API, dependency injection, OpenAPI docs |
| **SQLAlchemy 2 + Alembic** | ORM, migrations, encrypted DB fields |
| **Pydantic Settings** | Environment-driven configuration |
| **Groq SDK** | Chat/function-calling runtime and natural-language rule compilation |
| **httpx + tenacity** | External HTTP access and retry behavior |
| **PyMuPDF** | PDF text extraction |
| **PyCryptodome** | AES-GCM encryption |
| **python-jose + bcrypt** | JWT auth and password hashing |
| **ChromaDB** | Persistent academic vector/index store |
| **sentence-transformers + adapters** | SPECTER2 embeddings |
| **transformers + torch** | AI-writing detector model loading |
| **language_tool_python** | Local grammar review |
| **DrissionPage + Playwright runtime** | Live crawl/browser automation paths |

### Frontend

| Technology | Purpose |
|------------|---------|
| **Next.js 15 (App Router)** | UI shell, routing, rewrite proxy |
| **React 18** | Client UI |
| **TypeScript** | Typed frontend contracts |
| **Tailwind CSS v4** | Theme tokens and styling |
| **TanStack React Query** | Admin dashboard data fetching/caching |
| **Sonner** | Toasts |
| **Lucide React** | Icons |
| **Vitest + Testing Library** | Frontend tests |

### External Services and Data Sources

| Service | Current Use |
|---------|-------------|
| **Groq** | Chat completion, tool calling, simple generation, AI-rule compilation |
| **OpenAlex** | Scholarly metadata and verification |
| **Crossref** | DOI and retraction-related metadata |
| **Semantic Scholar** | Citation fallback / enrichment path |
| **PubPeer** | Retraction / community-signal scan |
| **Tavily** | Optional citation-only web fallback provider |
| **Hugging Face** | Model downloads |
| **AWS S3** | Optional object storage backend |
| **Clarivate APIs / manual imports** | Venue enrichment pipeline |

---

## 📌 Prerequisites

- **Python** 3.11+ (`3.12` recommended)
- **Node.js** 18+ (`20` recommended)
- **npm** 9+ or compatible package manager
- **Git**
- *(Optional but recommended)* **Java 17+** for LanguageTool
- *(Optional but recommended)* **Groq API key** for chat, summarization, and AI-rule compilation
- *(Optional)* **Hugging Face token** if your environment needs authenticated model download
- *(Optional)* Chromium/Playwright-compatible browser runtime for live academic crawl validation

---

## 🚀 Installation & Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Nhan-Laptop/NT208.Q21.ANTN.git
cd NT208.Q21.ANTN
```

### 2. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Database Migration

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

### 4. Optional Model Download

```bash
cd backend
source .venv/bin/activate
python scripts/download_detector_model.py
```

### 5. Frontend Setup

```bash
cd frontend
npm install
```

### 6. Environment Files

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Use the example files as the authoritative starting point; they already reflect the current config surface more accurately than older screenshots or notes.

---

## 🔑 Environment Variables

### Backend (`backend/.env`)

Key groups you will likely touch first:

```env
APP_ENV=development
DATABASE_URL=sqlite:///./aira.db

JWT_SECRET_KEY=replace-me-in-production
ADMIN_EMAIL=admin@aira.local
ADMIN_PASSWORD=ChangeMe!123

GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant

SEMANTIC_SCHOLAR_ENABLED=true
WEB_SEARCH_PROVIDER=disabled
TAVILY_API_KEY=

STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=local_storage

CHROMA_DB_PATH=data/chroma_db
ACADEMIC_LIVE_SOURCES_PATH=crawler/sources.json
AI_DETECT_ML_ENABLED=true
```

Important current notes:

- `backend/.env.example` includes the full up-to-date config surface for storage, crawl, AI detection, citation fallback, and security settings.
- Relative SQLite paths are normalized against `backend/`.
- `ACADEMIC_ENABLE_STARTUP_SCHEMA_CREATE=false` is the safer local default if you want Alembic-managed databases.
- `WEB_SEARCH_PROVIDER=tavily` only affects citation fallback; it does not expose general browsing to the chat runtime.

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Frontend still sends same-origin requests such as `/api/v1/...`; this variable is used by `next.config.mjs` rewrites to decide which backend to proxy to.

---

## ▶️ Running the Application

### Start the Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Useful backend URLs:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

### Start the Frontend

```bash
cd frontend
npm run dev
```

Frontend default URL:

- `http://localhost:3000`

### Quick Verification

1. Open `http://localhost:3000`.
2. Register or sign in.
3. Start a new chat and confirm a session is created.
4. Switch to `Xác minh trích dẫn` mode and paste a DOI or bibliography.
5. Switch to `Nhận diện văn bản AI` mode and confirm the AI rules panel loads.
6. Upload a file in an active chat session and confirm it appears as an encrypted attachment card.

---

## 🌐 Temporary Public Demo with ngrok

Recommended topology:

```text
https://<ngrok-domain>
  -> frontend :3000
  -> Next.js rewrite proxy
  -> backend :8000
```

This matches the current frontend architecture because:

- the browser only calls the frontend origin,
- `/api/v1/*` and `/health` are proxied by Next.js,
- you usually do not need to expose the backend directly for demos.

### Runbook

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd frontend
npm run dev
```

```bash
ngrok http 3000
```

### Demo Checklist

1. Landing page loads through the public URL.
2. Login/register works.
3. Chat request returns.
4. Verification mode works.
5. Journal match or AI detection mode returns structured cards.
6. File upload still works through the same public frontend URL.

---

## 📁 Project Structure

```text
NT208.Q21.ANTN/
├── README.md
├── architecture.md
├── frontend.md
├── module_tree.md
├── CODEX.md
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/      # auth, sessions, chat, tools, ai-detection, upload, manuscripts, journal-match, venues, crawl-admin, admin
│   │   ├── core/                  # config, security, authorization, crypto, middleware, rate limits, DB
│   │   ├── models/                # chat, file, user, venue, crawl, manuscript, AI-rule entities
│   │   ├── schemas/               # auth/chat/tools/upload/admin/academic/ai_detection schemas
│   │   └── services/              # chat, llm, file, storage, AI detection, academic query, journal_match, ingestion
│   ├── crawler/                   # live source registry, connectors, scheduler, scrape and index pipeline
│   ├── alembic/                   # migrations
│   ├── scripts/                   # keys, crawl tools, imports, audits, model download
│   ├── security/pentest/          # quick audit toolkit
│   └── tests/                     # backend regression and feature tests
├── frontend/
│   ├── app/                       # landing, login, chat, admin routes
│   ├── components/                # chat shell, tool cards, auth guard, AI rule UI
│   ├── lib/                       # API client, auth, chat store, hooks, exports, theme, types
│   └── *.config.*                 # Next/Vitest/PostCSS config
└── .git/
```

---

## 🔌 API Endpoints

### Core route groups

| Prefix | Purpose |
|--------|---------|
| `/api/v1/auth` | register, login, current-user profile, AI phrase-rule preferences, admin promote |
| `/api/v1/sessions` | create/list/update/delete sessions and list session messages |
| `/api/v1/chat` | chat completions, session-scoped completion, encrypted completion |
| `/api/v1/tools` | legacy chat-facing tool endpoints such as citation verification, journal match, retraction scan, summarize-pdf, AI detection, grammar |
| `/api/v1/ai-detection` | structured AI-rule compile/create/list/update/delete and direct analyze endpoint |
| `/api/v1/upload` | upload, list, stats, download, delete, presigned upload/download |
| `/api/v1/manuscripts` | manuscript upload and parse |
| `/api/v1/journal-match` | request/create, run, and fetch match results |
| `/api/v1/venues` | venue search |
| `/api/v1/crawl` and `/api/v1/crawl-admin` | run crawl, reindex, inspect jobs/sources |
| `/api/v1/admin` | overview, users, files, storage, storage health |

### Health

- `GET /health`

---

## 🧠 ML Models & AI Pipeline

### LLM and Tool Routing

- Primary chat/tool runtime: `GROQ_MODEL=llama-3.1-8b-instant`
- Function-calling orchestration lives in `backend/app/services/llm_service.py`
- Heuristic fallback and explicit deterministic paths prevent tool ambiguity for some academic intents

### Citation / Verification Pipeline

- Exact identifier verification for DOI / PMID / PMCID / OpenAlex ID
- Metadata parsing and scoring for no-DOI references
- Scholarly-source chain centered on Crossref, OpenAlex, DataCite, Semantic Scholar, publisher metadata, and optional constrained web fallback

### Journal / Venue Pipeline

- Embeddings centered on **SPECTER2**
- Persistent academic index in ChromaDB
- Crawl + ingest path through `backend/crawler/` and `backend/app/services/ingestion/`
- Dedicated `journal_match` service layer for manuscript parsing, retrieval, reranking, and explanation

### AI Writing Detection and Grammar

- RoBERTa-based ML detector with rule-based scoring blend
- Phrase-rule preferences stored per user
- Structured AI rules compiled from natural language
- Grammar checking via local LanguageTool runtime

---

## 🔒 Security Architecture

| Area | Current Control |
|------|-----------------|
| Authentication | JWT bearer auth via `python-jose` |
| Authorization | RBAC permissions + ABAC ownership checks |
| Message storage | Encrypted `content` and `tool_results` DB fields |
| File storage | AES-GCM encrypted storage with local/S3 abstraction |
| Request protection | Security headers + rate limiting middleware |
| Auditability | Structured audit events for auth/admin/file flows |
| Health exposure | Optional detail expansion; sensitive internals omitted by default |

For a quick non-destructive audit workflow, see [`backend/security/pentest/README.md`](./backend/security/pentest/README.md).

---

## 📖 Documentation

- [`architecture.md`](./architecture.md) — backend/system architecture snapshot
- [`frontend.md`](./frontend.md) — frontend architecture snapshot
- [`module_tree.md`](./module_tree.md) — citation-check module dependency map
- [`CODEX.md`](./CODEX.md) — source-of-truth notes for engineers and coding agents
- [`backend/security/pentest/README.md`](./backend/security/pentest/README.md) — quick audit usage

---

## 🗺️ Roadmap

- Add frontend surfaces for dedicated manuscript parsing, venue search, and crawl-admin operations already present in the backend.
- Harden journal-match and citation pipelines with broader end-to-end regression coverage.
- Improve background job visibility for crawl and reindex operations.
- Continue reducing documentation drift by treating code as the first source of truth.

---

## 🎥 Demo Video

[▶ Xem video demo](./docs/video_demo.mp4)

---

### Chúng em đã biết làm web và hiểu hệ thống web hoạt động như thế nào.
