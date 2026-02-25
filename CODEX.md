# AIRA Backend (FastAPI)

Backend cho đồ án `Academic Integrity & Research Assistant` - Nền tảng hỗ trợ viết và nộp bài báo khoa học đến các tạp chí và hội nghị uy tín.

## Tính năng chính

### 🗣️ Chat Management
- Chat sessions/messages lưu lịch sử hội thoại (context-aware)
- Full CRUD cho sessions (tạo/đọc/cập nhật/xóa)
- API đúng theo luồng chat dạng ChatGPT:
  - `POST /api/v1/chat/{session_id}` - Gửi tin nhắn
  - `POST /api/v1/chat/completions` - OpenAI-compatible endpoint
  - `GET/PATCH/DELETE /api/v1/sessions/{id}` - Quản lý session

### 🤖 AI/LLM Integration
- 3 mode chính:
  - `general_qa`: Hỏi đáp với Gemini (configurable `GEMINI_MODEL`, default `gemini-flash-latest`)
  - `verification`: Kiểm tra trích dẫn
  - `journal_match`: Gợi ý tạp chí theo abstract

### 🔬 Scientific Tools (V1 + V2 Enhanced)

| Tool | V1 (Basic) | V2 (Enhanced) |
|------|------------|---------------|
| **Citation Checker** | OpenAlex API | PyAlex + Habanero, multi-format (APA/IEEE/Vancouver) |
| **Journal Finder** | 5 journals, keyword matching | 35+ journals, SPECTER2/SciBERT embeddings |
| **Retraction Scanner** | OpenAlex + PubPeer | Crossref `update-to` field, risk levels |
| **AI Writing Detector** | Rule-based heuristics | RoBERTa GPT-2 detector + ensemble |

API endpoints:
- `POST /api/v1/tools/verify-citation` - Xác minh trích dẫn
- `POST /api/v1/tools/journal-match` - Gợi ý tạp chí phù hợp
- `POST /api/v1/tools/retraction-scan` - Quét bài bị rút
- `POST /api/v1/tools/summarize-pdf` - Tóm tắt PDF
- `POST /api/v1/tools/ai-detect` - Phát hiện văn bản AI

### 📁 File Storage
- Upload file PDF: `POST /api/v1/upload`
- Download file: `GET /api/v1/upload/{file_id}`
- S3 storage (hoặc local fallback)
- PDF text extraction bằng PyMuPDF
- Files mã hóa AES-256-GCM trước khi lưu

### 🔐 Security & Auth
- JWT Authentication + OAuth2
- RBAC + ABAC authorization
- AES-256-GCM encryption (at-rest và in-transit)
- In-memory rate limiting theo nhóm endpoint (`auth/chat/tools/upload`)
- Security headers middleware (CSP, nosniff, frame/referrer policy)
- CORS allowlist theo cấu hình env
- Audit logging cho auth/admin/file actions
- Role: `admin` / `researcher`

### 👔 Admin APIs
- `GET /api/v1/admin/overview` - Thống kê tổng quan
- `GET /api/v1/admin/users` - Danh sách users
- `POST /api/v1/auth/admin/promote` - Nâng quyền user

## Cấu trúc dự án

```text
backend/
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── core/
│   │   ├── config.py           # Settings từ .env
│   │   ├── security.py         # JWT, password hashing
│   │   ├── authorization.py    # RBAC + ABAC
│   │   ├── crypto.py           # AES-256-GCM encryption
│   │   ├── encrypted_types.py  # SQLAlchemy encrypted types
│   │   └── database.py         # Database connection
│   ├── models/
│   │   ├── user.py             # User model
│   │   ├── chat_session.py     # Session model
│   │   ├── chat_message.py     # Message model
│   │   └── file_attachment.py  # File attachment model
│   ├── schemas/
│   │   ├── auth.py             # Auth request/response
│   │   ├── chat.py             # Chat schemas
│   │   ├── tools.py            # Tool schemas
│   │   ├── upload.py           # Upload schemas
│   │   └── admin.py            # Admin schemas
│   ├── services/
│   │   ├── llm_service.py      # Gemini integration
│   │   ├── chat_service.py     # Chat logic
│   │   ├── file_service.py     # File upload/download
│   │   ├── bootstrap.py        # Admin auto-create
│   │   └── tools/
│   │       ├── citation_checker.py      # V1: Basic citation
│   │       ├── citation_checker_v2.py   # V2: PyAlex/Habanero
│   │       ├── journal_finder.py        # V1: Basic matching
│   │       ├── journal_finder_v2.py     # V2: SPECTER2/SciBERT
│   │       ├── retraction_scan.py       # V1: OpenAlex
│   │       ├── retraction_scan_v2.py    # V2: Crossref
│   │       ├── ai_writing_detector.py   # V1: Rule-based
│   │       └── ai_writing_detector_v2.py # V2: RoBERTa ML
│   └── api/v1/
│       ├── router.py           # API router
│       └── endpoints/
│           ├── auth.py         # Login/register
│           ├── sessions.py     # Session CRUD
│           ├── chat.py         # Chat endpoints
│           ├── tools.py        # Scientific tools
│           ├── upload.py       # File upload/download
│           └── admin.py        # Admin APIs
├── scripts/
│   └── generate_keys.py        # Security key generator
├── ARCHITECTURE.md
├── SECURITY_CRYPTOGRAPHY.md
├── requirements.txt
└── .env.example
```

### Frontend Structure

```text
frontend/
├── app/
│   ├── page.tsx                   # Landing page (Bohrium-like)
│   ├── login/page.tsx             # Login + Register tabs
│   ├── chat/layout.tsx            # Auth shell + sidebar sessions
│   ├── chat/page.tsx              # Workspace empty state
│   ├── chat/[sessionId]/page.tsx  # Chat UI + Tools/Files panel
│   └── admin/page.tsx             # Admin dashboard
├── components/
│   ├── auth-guard.tsx
│   ├── chat-shell.tsx
│   └── topbar.tsx
├── lib/
│   ├── api.ts                     # Typed API client
│   ├── auth.tsx                   # In-memory bearer auth context
│   └── types.ts                   # Shared types
└── .env.example
```

## Cài đặt và chạy

### Yêu cầu
- Python 3.10+
- pip
- Node.js 18+ (để chạy frontend)

### Chạy nhanh (Backend + Frontend)

Nếu repo đã có sẵn `backend/.env` (có API keys/credentials), **không ghi đè** file này.  
Frontend dùng `frontend/.env.local` (không commit).

1) Backend:
```bash

cd backend
source .venv/bin/activate  # nếu chưa có: python3 -m venv .venv
# pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

```

2) Frontend:
```bash

cd frontend
npm install
cp .env.example .env.local
npm run dev -- --hostname 127.0.0.1 --port 3000

```

3) Mở trình duyệt:
- Landing: `http://127.0.0.1:3000/`
- Login/Register: `http://127.0.0.1:3000/login` (tab register: `?tab=register`)
- Workspace: `http://127.0.0.1:3000/chat`
- Swagger: `http://127.0.0.1:8000/docs`

### Lưu ý CORS/Port
- Frontend gọi API theo same-origin (`/api/v1/...`) và Next.js sẽ **proxy** request sang backend (rewrites trong `frontend/next.config.mjs`).
- Vì vậy khi chạy demo qua HTTPS (ngrok/custom domain) sẽ **không bị CORS/mixed-content** và không cần expose backend ra internet.
- Backend CORS allowlist vẫn giữ để phòng trường hợp bạn gọi backend trực tiếp từ browser (vd: app khác, hoặc debug cross-origin).

### Demo Public Qua ngrok (1 URL)
Giả sử backend chạy local `127.0.0.1:8000` và frontend chạy local `127.0.0.1:3000`:
```bash
ngrok http 3000
```
Mở URL `https://<something>.ngrok-free.dev` và test:
- Login/Register
- Chat + Tools
- Upload attachment (frontend sẽ proxy qua backend)

### Smoke test/Pentest nhanh (không phá hoại)
```bash
cd backend
source .venv/bin/activate
python security/pentest/quick_audit.py --base-url http://127.0.0.1:8000
```

## Frontend Notes

### Auth UX
- Trang `/login` có 2 tab: `Đăng nhập` và `Đăng ký` (deep-link: `/login?tab=register`).
- Backend đã có `POST /api/v1/auth/register`, frontend gọi `register -> login` để vào thẳng workspace.
- Token giữ **in-memory** theo plan (không localStorage/cookie), nên reload sẽ mất session.

### Bohrium-like Layout
- `/chat/*` dùng layout 2 cột: sidebar (sessions + create) + main (chat/tools/files).
- Panel của session có tabs: `Tools` và `Files`.
- Kết quả tools render theo `message_type` và `tool_results` (table/JSON fallback).

## Recent Changes (2026-02-14)

- Frontend:
  - Làm landing page kiểu Bohrium tại `/` và nâng cấp theme (fonts + UI shell).
  - Thêm tab `Đăng ký` ngay trên `/login` (không còn “chỉ có đăng nhập”).
  - Refactor `/chat` sang shell layout: sidebar sessions + main chat + panel tools/files.
  - Thêm `api.getSession(...)` để lấy session detail (title/mode) và đổi mode trực tiếp trên UI.
- Backend:
  - Harden LLM integration: nếu Gemini model/key lỗi, chat/summarize trả fallback text thay vì crash `500` (`backend/app/services/llm_service.py`).

### Cài đặt cơ bản
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Chỉnh sửa .env với credentials của bạn
```

### Tạo security keys
```bash
python scripts/generate_keys.py
# Copy output vào file .env
```

### Chạy server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Health check
```
GET http://localhost:8000/health
```

### API Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Biến môi trường

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLite/PostgreSQL connection | `sqlite:///./aira.db` |
| `JWT_SECRET_KEY` | JWT signing key | (required) |
| `ADMIN_EMAIL` | Admin bootstrap email | `admin@aira.local` |
| `ADMIN_PASSWORD` | Admin bootstrap password | `ChangeMe!123` |
| `ADMIN_MASTER_KEY_B64` | AES encryption key (base64) | Auto-generated |
| `GOOGLE_API_KEY` | Google Gemini API key | (required for LLM) |
| `AWS_ACCESS_KEY_ID` | S3 access key | (optional) |
| `AWS_SECRET_ACCESS_KEY` | S3 secret key | (optional) |
| `S3_BUCKET_NAME` | S3 bucket name | (optional) |

## Lưu ý bảo mật

⚠️ **Quan trọng cho production:**

1. **HTTPS bắt buộc** - Deploy sau reverse proxy có TLS
2. **Đổi JWT_SECRET_KEY** - Không dùng key mặc định
3. **Key management** - Dùng AWS KMS hoặc HashiCorp Vault
4. **Tách môi trường** - Dev/staging/prod riêng biệt
5. **Rate limiting** - Bật brute-force protection

## Dependencies chính

### Core
- FastAPI, Uvicorn, SQLAlchemy, Pydantic

### Security
- python-jose (JWT), bcrypt, PyCryptodome (AES)

### AI/ML (V2 modules)
- sentence-transformers (SPECTER2/SciBERT)
- transformers (RoBERTa)
- pyalex, habanero (API wrappers)

### File handling
- boto3 (S3), PyMuPDF (PDF)

---

## 📋 TODO List

### 🔴 High Priority
- [ ] Migrate từ `google-generativeai` sang `google-genai` SDK mới
- [ ] Thêm Alembic database migrations
- [ ] Viết unit tests cho authorization flows
- [ ] Frontend polish: tool result render theo component (citation/journal/retraction), không chỉ table/JSON

### 🟡 Medium Priority
- [ ] Redis cache cho session context
- [ ] WebSocket support cho real-time chat
- [ ] Vector database (Qdrant/PGVector) cho journal recommendations
- [ ] Batch citation verification endpoint
- [ ] Export chat history (PDF/Markdown)

### 🟢 Nice to Have
- [ ] Queue system (Celery/RQ) cho heavy jobs
- [ ] Audit logging với SIEM integration
- [ ] Key rotation automation
- [ ] Multi-language support (i18n)
- [ ] Dark mode API preferences

### 🔵 Frontend Integration
- [ ] Admin dashboard với charts
- [ ] Real-time notification system
- [ ] File preview component
- [ ] Citation format selector UI
- [ ] Journal recommendation wizard

### ✅ Completed
- [x] Chat management với full CRUD
- [x] Session management (GET/PATCH/DELETE)
- [x] File download endpoint
- [x] AI Writing Detector (v1 + v2)
- [x] Enhanced Journal Finder (35+ journals, SPECTER2)
- [x] Enhanced Citation Checker (PyAlex/Habanero)
- [x] Enhanced Retraction Scanner (Crossref)
- [x] Security key generation script
- [x] Security headers + CORS allowlist
- [x] In-memory rate limiting cho endpoints trọng yếu
- [x] API alias `POST /api/v1/tools/ai-detect`
- [x] Pentest quick-audit toolkit (`security/pentest`)
- [x] Comprehensive documentation
- [x] Frontend MVP: Landing + Login/Register + Chat shell + Tools/Files panel + Admin page
