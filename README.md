<p align="center">
  <img src="https://img.shields.io/badge/AIRA-Academic%20Integrity%20%26%20Research%20Assistant-blue?style=for-the-badge&logo=bookstack&logoColor=white" alt="AIRA Badge"/>
</p>

<h1 align="center">🎓 AIRA — Academic Integrity & Research Assistant</h1>

<p align="center">
  <strong>All-in-one AI-powered research platform — Citation Verification, Journal Matching, Retraction Scanning, AI Writing Detection, and PDF Summarization in a unified ChatGPT-style interface.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Next.js_15-000000?style=flat-square&logo=next.js&logoColor=white" alt="Next.js"/>
  <img src="https://img.shields.io/badge/React_18-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React"/>
  <img src="https://img.shields.io/badge/Tailwind_CSS_v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind"/>
  <img src="https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=google&logoColor=white" alt="Gemini"/>
  <img src="https://img.shields.io/badge/HuggingFace-FFD21E?style=flat-square&logo=huggingface&logoColor=black" alt="HuggingFace"/>
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
- [Project Structure](#-project-structure)
- [API Endpoints](#-api-endpoints)
- [ML Models & AI Pipeline](#-ml-models--ai-pipeline)
- [Security Architecture](#-security-architecture)
- [Documentation](#-documentation)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 🌟 Overview

**AIRA** (Academic Integrity & Research Assistant) is a web-based platform that integrates AI chatbot capabilities with specialized academic research tools. Instead of switching between 5–6 separate services (ChatGPT, Scimago, OpenAlex, GPTZero, Retraction Watch…), researchers get everything in a single, encrypted, ChatGPT-style interface.

### 🎯 The Problem

- Researchers use **multiple disconnected tools** for literature verification, journal selection, and integrity checks.
- No existing platform offers **citation verification + journal recommendation + retraction scanning + AI text detection** in one UI.
- Sensitive research data is sent unencrypted to various third-party services.

### 💡 The Solution

AIRA combines **6 research tools** with a conversational AI interface, featuring end-to-end encryption (AES-256-GCM) and a self-hosted architecture — giving researchers full control over their data.

---

## ✨ Key Features

| Feature | Description | Powered By |
|---------|-------------|------------|
| 💬 **General Q&A** | Conversational AI for research questions, with context memory (8 messages) and file-aware responses | Google Gemini |
| 📝 **Citation Verification** | Extract citations (APA, IEEE, Vancouver, DOI) from text → verify against authoritative databases → detect hallucinated references | OpenAlex + Crossref |
| 📚 **Journal Matching** | Paste your abstract → get top-5 journal recommendations ranked by semantic similarity, impact factor, and domain match | SPECTER2 / SciBERT |
| 🔍 **Retraction Scanning** | Check DOIs against retraction databases → multi-source risk assessment (NONE → CRITICAL) | Crossref + OpenAlex + PubPeer |
| 🤖 **AI Writing Detection** | Ensemble analysis: 70% RoBERTa ML classifier + 30% rule-based heuristics (7 linguistic features) → 5-level verdict scale | RoBERTa + Custom Rules |
| 📄 **PDF Summarization** | Upload PDF → automatic text extraction → AI-powered summary generation | PyMuPDF + Gemini |
| 🔐 **End-to-End Encryption** | 5-layer security: HTTPS → JWT (HS256) → DB encryption (AES-256-GCM) → File encryption → Optional client-side payload encryption | PyCryptodome |
| 🌙 **Dark Mode** | System preference detection + manual toggle, powered by Tailwind CSS v4 design tokens | Tailwind v4 |
| 👤 **Admin Dashboard** | Real-time overview (users, sessions, files, storage), user management, audit logging | React Query |

---

## 🏛️ System Architecture

AIRA follows a **Modular Monolith + Layered Architecture** pattern:

```
┌─────────────────────────────────────────────────────────────────┐
│  CLIENT (Browser)                                               │
│  Next.js 15 + React 18 + TypeScript + Tailwind CSS v4           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Landing  │ │  Login/  │ │   Chat   │ │  Admin   │           │
│  │  Page    │ │ Register │ │   View   │ │Dashboard │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└──────────────────────────────┬──────────────────────────────────┘
                               │ Next.js Proxy Rewrites
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI + Python 3.12)                                 │
│  Middleware: SecurityHeaders → RateLimit → CORS → JWT Auth       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  API Router (v1): auth │ sessions │ chat │ tools │      │     │
│  │                        upload │ admin                    │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │  Services: ChatService │ FileService │ GeminiService     │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │  ML Tools: JournalFinder │ CitationChecker │             │     │
│  │            RetractionScanner │ AIWritingDetector          │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │  Storage: S3 / Local (Strategy Pattern) + AES-256-GCM   │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │  ORM: SQLAlchemy 2.0 + EncryptedText/EncryptedJSON      │     │
│  └─────────────────────────────────────────────────────────┘     │
│                              │                                    │
└──────────────────────────────┼────────────────────────────────────┘
                               ▼
              ┌───────────────────────────────┐
              │  SQLite (dev) / PostgreSQL    │
              │  External: Gemini, OpenAlex,  │
              │  Crossref, PubPeer, AWS S3    │
              └───────────────────────────────┘
```

> 📖 **Deep-dive documentation:** See [`architecture.md`](./architecture.md) for full backend architecture with 10+ Mermaid diagrams, and [`frontend.md`](./frontend.md) for the complete frontend architecture (1000+ lines, 10 Mermaid diagrams).

---

## 🛠️ Tech Stack

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.12 | Runtime |
| **FastAPI** | ≥0.115 | Web framework, auto-generated OpenAPI docs |
| **SQLAlchemy** | ≥2.0.30 | ORM with transparent encryption (custom TypeDecorators) |
| **Pydantic** | v2 | Request/response validation, settings management |
| **Google GenAI SDK** | ≥1.0.0 | Gemini LLM integration (chat + summarization + function calling) |
| **Sentence-Transformers** | ≥2.2.0 | SPECTER2 / SciBERT embedding models |
| **Transformers + PyTorch** | ≥4.35 / ≥2.0 | RoBERTa AI writing detection pipeline |
| **PyAlex** | ≥0.13 | OpenAlex API wrapper (citation verification) |
| **Habanero** | ≥1.2.0 | Crossref API wrapper (DOI verification, retraction scan) |
| **PyMuPDF** | ≥1.24 | PDF text extraction |
| **PyCryptodome** | ≥3.20 | AES-256-GCM encryption primitives |
| **python-jose** | ≥3.3.0 | JWT token signing/verification (HS256) |
| **bcrypt** | ≥4.1.0 | Password hashing |
| **boto3** | ≥1.34 | AWS S3 storage backend (optional) |
| **httpx** | ≥0.27 | Async HTTP client with retry transport |
| **scikit-learn** | ≥1.3 | TF-IDF fallback for journal matching |

### Frontend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Next.js** | 15 | React framework (App Router, SSR, API proxy rewrites) |
| **React** | 18 | UI library (`useReducer` + Context for state management) |
| **TypeScript** | 5.6 | Type safety across 25+ API methods and 10 interfaces |
| **Tailwind CSS** | v4 | Utility-first CSS with `@theme` design tokens, dark mode |
| **TanStack React Query** | 5.62 | Server-state caching (Admin dashboard) |
| **Sonner** | 2.0 | Toast notifications for API errors |
| **Lucide React** | 0.564 | Icon library |

### External Services

| Service | Purpose | Notes |
|---------|---------|-------|
| **Google Gemini** | LLM (chat, summarization, function calling) | Free tier: 60 req/min |
| **OpenAlex** | Scholarly metadata (250M+ works) | Free, no API key required |
| **Crossref** | DOI verification, retraction metadata | Free, `update-to` field for retraction detection |
| **PubPeer** | Post-publication peer review comments | Free, community-driven early warnings |
| **AWS S3** | Object storage (optional) | Fallback: local filesystem |

---

## 📌 Prerequisites

- **Python** 3.11+ (3.12 recommended)
- **Node.js** 18+ (20 LTS recommended)
- **npm** 9+ or **pnpm**
- **Git**
- *(Optional)* A [Google AI Studio API Key](https://aistudio.google.com/apikey) for Gemini LLM features
- *(Optional)* A [Hugging Face Token](https://huggingface.co/settings/tokens) for authenticated model downloads

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

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install core dependencies
pip install -r requirements.txt

# (Optional) Install ML models for enhanced features
pip install sentence-transformers transformers torch huggingface-hub peft
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
```

### 4. Configure Environment Variables

```bash
# Backend
cp backend/.env.example backend/.env
# Edit backend/.env with your API keys (see Environment Variables section)

# Frontend
cp frontend/.env.example frontend/.env.local
# Edit frontend/.env.local
```

---

## 🔑 Environment Variables

### Backend (`backend/.env`)

```env
# === Application ===
APP_ENV=development
DEBUG=true

# === Database ===
DATABASE_URL=sqlite:///./aira.db
# For PostgreSQL: DATABASE_URL=postgresql://user:pass@localhost:5432/aira

# === JWT Authentication ===
JWT_SECRET_KEY=your-secure-random-string-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# === Admin Bootstrap ===
ADMIN_EMAIL=admin@aira.local
ADMIN_PASSWORD=ChangeMe!123

# === Google Gemini LLM ===
GOOGLE_API_KEY=your-google-ai-studio-api-key

# === Hugging Face (Optional - for ML model downloads) ===
HF_TOKEN=hf_your_token_here

# === AWS S3 Storage (Optional - defaults to local filesystem) ===
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-southeast-1
S3_BUCKET_NAME=

# === Security ===
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
RATE_LIMIT_ENABLED=true

# === AES-256-GCM Master Key (auto-generated if not set) ===
# ADMIN_MASTER_KEY_B64=
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

> **Note:** The Next.js proxy rewrites in `next.config.mjs` handle API routing automatically. The frontend proxies all `/api/v1/*` requests to the backend, so the browser only connects to a single origin.

---

## ▶️ Running the Application

### Start the Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at `http://localhost:8000` with auto-generated API docs at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Start the Frontend

```bash
cd frontend
npm run dev
```

The frontend will be available at `http://localhost:3000`.

### Quick Verification

1. Open `http://localhost:3000` → You should see the AIRA landing page.
2. Click **Get Started** → Register a new account.
3. You'll be redirected to the chat interface → Try sending a message!
4. Switch modes using the dropdown (General Q&A → Verification → Journal Match).

---

## 📁 Project Structure

```
NT208.Q21.ANTN/
├── README.md                  # ← You are here
├── architecture.md            # Backend architecture (3000+ lines, 10+ Mermaid diagrams)
├── frontend.md                # Frontend architecture (1000+ lines, 10 Mermaid diagrams)
├── CLAUDE.md                  # Session audit log & project status
├── CODEX.md                   # AI coding guidelines
│
├── backend/
│   ├── requirements.txt       # Python dependencies
│   ├── app/
│   │   ├── main.py            # FastAPI app entry, lifespan, middleware stack
│   │   ├── core/
│   │   │   ├── config.py      # Pydantic Settings (env loading, validation)
│   │   │   ├── security.py    # JWT creation/verification, bcrypt
│   │   │   ├── authorization.py  # RBAC (6 permissions) + ABAC (ownership)
│   │   │   ├── crypto.py      # AES-256-GCM master key manager
│   │   │   ├── encrypted_types.py  # SQLAlchemy EncryptedText/EncryptedJSON
│   │   │   ├── middleware.py   # Security headers + rate limiting
│   │   │   ├── rate_limit.py   # Fixed-window rate limiter
│   │   │   ├── database.py    # SQLAlchemy engine + session factory
│   │   │   └── audit.py       # Rotating audit log
│   │   ├── models/            # SQLAlchemy ORM models (4 tables)
│   │   │   ├── user.py
│   │   │   ├── chat_session.py
│   │   │   ├── chat_message.py   # EncryptedText content, EncryptedJSON tool_results
│   │   │   └── file_attachment.py
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   │   ├── auth.py, chat.py, tools.py, upload.py, admin.py
│   │   │   └── __init__.py
│   │   ├── api/v1/
│   │   │   ├── router.py      # Central router (6 endpoint modules)
│   │   │   └── endpoints/
│   │   │       ├── auth.py    # register, login, me, promote (4 endpoints)
│   │   │       ├── sessions.py  # CRUD sessions + list messages (6 endpoints)
│   │   │       ├── chat.py    # chat completions + encrypted variant (3 endpoints)
│   │   │       ├── tools.py   # 6 tool endpoints (citation, journal, retraction, AI, PDF)
│   │   │       ├── upload.py  # file upload/download/stats (8 endpoints)
│   │   │       └── admin.py   # dashboard, users, files, storage (7 endpoints)
│   │   └── services/
│   │       ├── chat_service.py     # Mode-based routing, context building
│   │       ├── llm_service.py      # Gemini LLM (google-genai SDK)
│   │       ├── file_service.py     # Upload, PDF extraction, stats
│   │       ├── storage_service.py  # S3/Local dual-backend + encryption
│   │       ├── bootstrap.py        # Auto-create admin on startup
│   │       └── tools/
│   │           ├── journal_finder.py       # SPECTER2/SciBERT + TF-IDF fallback
│   │           ├── citation_checker.py     # PyAlex + Habanero multi-source
│   │           ├── retraction_scan.py      # Crossref + OpenAlex + PubPeer
│   │           └── ai_writing_detector.py  # RoBERTa ensemble + 7 heuristics
│   ├── scripts/
│   │   └── generate_keys.py  # AES master key generator
│   └── security/
│       └── pentest/
│           ├── quick_audit.py   # Non-destructive security audit script
│           └── README.md
│
├── frontend/
│   ├── package.json
│   ├── next.config.mjs        # API proxy rewrites
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   ├── app/
│   │   ├── layout.tsx         # Root layout (Inter font, providers)
│   │   ├── page.tsx           # Landing page (feature cards)
│   │   ├── providers.tsx      # QueryClient → Theme → Auth → Toaster
│   │   ├── globals.css        # Tailwind v4 @theme tokens (30 CSS vars)
│   │   ├── login/page.tsx     # Login/Register tabbed form
│   │   ├── chat/
│   │   │   ├── layout.tsx     # AuthGuard → ChatProvider → Sidebar
│   │   │   ├── page.tsx       # New conversation view
│   │   │   └── [sessionId]/page.tsx  # Existing session view
│   │   └── admin/page.tsx     # Admin dashboard (React Query)
│   ├── components/
│   │   ├── chat-view.tsx      # ChatView, InputArea, MessageBubble (~500 LOC)
│   │   ├── chat-shell.tsx     # Sidebar: sessions, search, theme toggle (~300 LOC)
│   │   ├── tool-results.tsx   # 6 rich tool result cards (~520 LOC)
│   │   ├── topbar.tsx         # ModeSelector dropdown (5 modes)
│   │   └── auth-guard.tsx     # Route protection + admin check
│   ├── hooks/
│   │   ├── useAutoScroll.ts   # Smart scroll on new messages only
│   │   └── useFileUpload.ts   # Drag-and-drop + progress tracking
│   └── lib/
│       ├── api.ts             # 25+ typed API methods + error handling (~280 LOC)
│       ├── auth.tsx           # AuthContext (login/register/logout)
│       ├── chat-store.tsx     # useReducer (11 actions), auto-session creation
│       ├── theme.tsx          # ThemeProvider (dark/light + system preference)
│       └── types.ts           # 10 TypeScript interfaces
│
└── local_storage/             # Default file storage directory (dev)
```

---

## 🔌 API Endpoints

**34 endpoints** across 6 modules under `/api/v1`:

| Module | Endpoints | Key Routes |
|--------|-----------|------------|
| **Auth** | 4 | `POST /register`, `POST /login`, `GET /me`, `POST /admin/promote` |
| **Sessions** | 6 | `POST/GET/PATCH/DELETE /sessions`, `GET /sessions/{id}/messages` |
| **Chat** | 3 | `POST /chat/{session_id}`, `POST /chat/completions`, `POST /chat/completions/encrypted` |
| **Tools** | 6 | `POST /tools/verify-citation`, `/journal-match`, `/retraction-scan`, `/detect-ai-writing`, `/ai-detect`, `/summarize-pdf` |
| **Upload** | 8 | `POST/GET/DELETE /upload`, `GET /upload/stats/*`, presigned URL support |
| **Admin** | 7 | `GET /admin/overview`, `/users`, `/files`, `/storage`, `DELETE /admin/files/{id}` |

> Full OpenAPI documentation is auto-generated at `/docs` (Swagger) and `/redoc` when the backend is running.

---

## 🧠 ML Models & AI Pipeline

### Model Inventory

| Model | Parameters | Purpose | Latency |
|-------|-----------|---------|---------|
| **SPECTER2** (`allenai/specter2_base`) | 110M | Scientific paper embeddings (768-dim) for journal matching | ~3.9s (first load) |
| **SciBERT** (`allenai/scibert_scivocab_uncased`) | 110M | Fallback embeddings with science-optimized vocabulary | ~3s |
| **RoBERTa** (`roberta-base-openai-detector`) | 125M | Binary classifier: Human vs AI-generated text | ~4.8s (first load) |
| **all-MiniLM-L6-v2** | 22M | Ultimate fallback: general-purpose sentence embeddings | ~1s |

### Fallback Chain (Graceful Degradation)

```
Journal Matching:  SPECTER2 → SciBERT → MiniLM-L6-v2 → TF-IDF (no ML)
AI Detection:      RoBERTa ensemble (70/30) → Rule-based only (no ML)
```

All ML models load with `local_files_only=True` retry — if network is unavailable, cached models are used automatically.

### AI Writing Detection — Ensemble Method

The ensemble combines:
- **70% ML Score**: RoBERTa classifier (trained on GPT-2 output)
- **30% Rule Score**: 7 weighted linguistic heuristics (sentence uniformity, vocabulary diversity, AI-typical patterns, filler phrase density, transition word density, sentence repetition, hapax ratio)

| Final Score | Verdict |
|-------------|---------|
| < 0.25 | LIKELY_HUMAN |
| 0.25 – 0.40 | POSSIBLY_HUMAN |
| 0.40 – 0.60 | UNCERTAIN |
| 0.60 – 0.75 | POSSIBLY_AI |
| ≥ 0.75 | LIKELY_AI |

---

## 🔒 Security Architecture

### 5-Layer Encryption Model

| Layer | Technology | Scope |
|-------|-----------|-------|
| **Layer 1** — Transit | HTTPS + CSP + HSTS + Security Headers | All HTTP traffic |
| **Layer 2** — Authentication | JWT (HS256) with `iat`/`jti`/`exp` claims, 1h TTL | API access control |
| **Layer 3** — Database | AES-256-GCM via SQLAlchemy `EncryptedText`/`EncryptedJSON` | Messages, file metadata |
| **Layer 4** — File Storage | AES-256-GCM file encryption (S3/Local) | Uploaded files |
| **Layer 5** — Optional | Client-side AES-256-GCM encrypted payloads (AAD = user_id) | End-to-end chat |

### Authorization Model

- **RBAC**: 2 roles (`ADMIN`, `RESEARCHER`) → 6 permissions (`session:read`, `session:write`, `message:write`, `tool:execute`, `file:upload`, `admin:manage`)
- **ABAC**: Ownership-based access control — users can only access their own sessions/files, admins bypass ownership checks
- **Rate Limiting**: Fixed-window limiter per bucket (auth: 10/min, chat: 60/min, tools: 40/min, upload: 20/min)

### Security Audit

A built-in pentest toolkit (`backend/security/pentest/`) runs 7 non-destructive checks:
- Health info disclosure, IDOR (sessions/messages), privilege escalation, encrypted payload tampering, login rate limiting, file upload spoofing

```bash
cd backend && source .venv/bin/activate
python security/pentest/quick_audit.py --base-url http://localhost:8000
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [**architecture.md**](./architecture.md) | Complete backend architecture — data models, service layer, tool pipelines, Gemini Function Calling, security design (3000+ lines, 10+ Mermaid diagrams) |
| [**frontend.md**](./frontend.md) | Complete frontend architecture — provider tree, routing, state management, components, hooks, theming (1000+ lines, 10 Mermaid diagrams) |
| [**CLAUDE.md**](./CLAUDE.md) | Session audit log — all changes, fixes, and decisions across development sessions |

---

## 🗺️ Roadmap

### ✅ Completed (MVP)

- [x] JWT Authentication + RBAC/ABAC authorization
- [x] Chat AI with Google Gemini (context memory, file-aware responses)
- [x] Citation Verification (6 regex patterns, OpenAlex + Crossref)
- [x] Journal Matching (SPECTER2/SciBERT embeddings, 35 journals)
- [x] Retraction Scanning (Crossref + OpenAlex + PubPeer, risk levels)
- [x] AI Writing Detection (RoBERTa ensemble, 7 heuristics)
- [x] PDF Summarization (PyMuPDF + Gemini)
- [x] File Upload/Download with AES-256-GCM encryption
- [x] Admin Dashboard (overview, users, files, storage)
- [x] Dark/Light mode with system preference
- [x] Security hardening (38 audit issues → 28+ fixed)
- [x] Gemini Function Calling integration

### 🔴 High Priority

- [ ] Alembic database migrations
- [ ] Token revocation (Redis blacklist)
- [ ] Async refactor (`async def` endpoints, `httpx.AsyncClient`)
- [ ] Unit tests (pytest + Jest, target 80% coverage)

### 🟡 Medium Priority

- [ ] Redis caching for tool results
- [ ] WebSocket streaming (real-time AI responses)
- [ ] httpOnly cookie authentication
- [ ] Mobile-responsive sidebar

### 🟢 Low Priority

- [ ] E2E tests (Playwright)
- [ ] Vector database (Qdrant) for semantic paper search
- [ ] i18n (full Vietnamese + English)
- [ ] Email notifications (confirmation, password reset)

---

## 📄 License

This project was developed as part of the **NT208 — Web Application Development** course at UIT (University of Information Technology, VNU-HCM).

---

<p align="center">
  Made with ❤️ by the AIRA Team
</p>
