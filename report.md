# AIRA (Academic Integrity & Research Assistant) – Tổng Quan Đồ Án

Ngày cập nhật: 2026-02-14

## 1) Mục tiêu & phạm vi

AIRA là nền tảng web dạng hội thoại (chat-based) để hỗ trợ nghiên cứu khoa học:

- Quản lý phiên chat (sessions) và lịch sử hội thoại (messages) theo ngữ cảnh.
- Tích hợp LLM (Google Gemini) cho chế độ hỏi đáp và tóm tắt.
- Tích hợp các tools chuyên sâu (trích dẫn, gợi ý tạp chí, quét retraction, AI writing detect).
- Upload/Download file (PDF) + trích xuất text + lưu trữ dữ liệu nặng trên S3 (hoặc local fallback).
- Bảo mật: JWT auth, phân quyền RBAC + ABAC, mã hóa AES-256-GCM (dữ liệu nghỉ và payload mã hóa tùy chọn).

## 2) Kiến trúc tổng thể

Kiến trúc chính: **Modular Monolith + Layered Architecture**.

- Frontend: Next.js (App Router) + TypeScript + React Query.
- Backend: FastAPI + SQLAlchemy + Pydantic.
- Database: PostgreSQL (production) / SQLite (dev).
- Storage: AWS S3 (primary cho dữ liệu nặng/backup) hoặc Local Storage (dev).
- External APIs: Google Gemini, OpenAlex/Crossref/PubPeer (tools).

Sơ đồ node (hệ thống runtime):

1. Browser (User/Admin)
2. Next.js Frontend (`/frontend`)
3. FastAPI Backend (`/backend`)
4. Database (Users/Sessions/Messages/Files)
5. Object Storage (S3 hoặc local)
6. LLM Provider (Google Gemini)
7. Tool Providers (OpenAlex, Crossref, PubPeer)

## 3) Database & phân quyền (RBAC + ABAC)

### Bảng chính (SQLAlchemy)

- `users`:
  - Lưu tài khoản người dùng và admin.
  - Trường `role` lưu trong DB (`admin` | `researcher`) để phân quyền.
  - File: `backend/app/models/user.py`.

- `chat_sessions`:
  - Lưu danh sách phiên chat (sidebar).
  - Mỗi session thuộc về 1 user (`user_id`).
  - File: `backend/app/models/chat_session.py`.

- `chat_messages`:
  - Lưu lịch sử hội thoại theo session.
  - Có `role` (`user/assistant/system/tool`) và `message_type` để frontend render component.
  - File: `backend/app/models/chat_message.py`.

- `file_attachments`:
  - Metadata file upload gắn với session/message.
  - Dữ liệu nặng nằm ở object storage; DB chỉ lưu metadata (đã mã hóa).
  - File: `backend/app/models/file_attachment.py`.

### Phân quyền

- RBAC:
  - Mapping permission theo role tại `backend/app/core/authorization.py` (`ROLE_PERMISSIONS`).
  - Admin có `admin:manage` và quyền truy cập rộng hơn.

- ABAC (ownership/resource access):
  - `assert_session_access`, `assert_message_access`, `assert_file_access` bảo đảm user chỉ truy cập tài nguyên của mình.
  - File: `backend/app/core/authorization.py`.

## 4) Cryptography & bảo mật dữ liệu

### Master key (AES-256-GCM)

- Master key 32 bytes (base64 urlsafe) được load từ:
  - `ADMIN_MASTER_KEY_B64` trong env, hoặc
  - file `MASTER_KEY_FILE` (mặc định `.aira_master_key`), hoặc
  - auto-generate khi thiếu (tạo file và set permission 0600).
- File: `backend/app/core/crypto.py`.

### Mã hóa dữ liệu nghỉ (At-rest encryption)

- DB encryption:
  - `EncryptedText` và `EncryptedJSON` mã hóa trước khi ghi DB và giải mã khi đọc.
  - Áp dụng cho:
    - `chat_messages.content`, `chat_messages.tool_results`
    - `file_attachments.storage_key`, `storage_url`, `extracted_text`
  - File: `backend/app/core/encrypted_types.py`, `backend/app/models/chat_message.py`, `backend/app/models/file_attachment.py`.

- Storage encryption:
  - File bytes được mã hóa AES-256-GCM trước khi lưu vào S3/local (storage_service).
  - File: `backend/app/services/storage_service.py`.

### Mã hóa dữ liệu khi gửi đi (In-transit)

- TLS/HTTPS: bắt buộc khi deploy production (reverse proxy).
- Application-layer encryption (tùy chọn):
  - `POST /api/v1/chat/completions/encrypted` nhận/gửi payload đã mã hóa AES-256-GCM.
  - AAD ràng buộc theo `current_user.id` để chống chuyển payload giữa user.
  - File: `backend/app/api/v1/endpoints/chat.py`, `backend/app/core/crypto.py`.

### Hardening

- Security headers middleware + CORS allowlist:
  - `backend/app/core/middleware.py`, `backend/app/main.py`, `backend/app/core/config.py`.
- Rate limiting in-memory theo bucket `auth/chat/tools/upload`:
  - `backend/app/core/rate_limit.py`.
- Audit logs (file rotating) cho auth/admin/file actions:
  - `backend/app/core/audit.py`.

## 5) Modules: chức năng, nhiệm vụ, tương tác

Tổng số module chính (khái niệm): **10**.

### Module A – Auth & Users

- Nhiệm vụ:
  - Register/Login/Me
  - Bootstrap admin user
  - Promote role (admin-only)
- Tương tác:
  - API -> DB (`users`) -> JWT token
- Files:
  - `backend/app/api/v1/endpoints/auth.py`
  - `backend/app/core/security.py`
  - `backend/app/services/bootstrap.py`

### Module B – Authorization Gateway (RBAC + ABAC)

- Nhiệm vụ:
  - Bảo vệ toàn bộ endpoint theo permission và ownership
- Files:
  - `backend/app/core/authorization.py`

### Module C – Chat Management (Sessions/Messages)

- Nhiệm vụ:
  - CRUD sessions + list messages
  - Persist messages theo dạng hội thoại
  - Message types để frontend render
- Files:
  - `backend/app/services/chat_service.py`
  - `backend/app/api/v1/endpoints/sessions.py`
  - `backend/app/api/v1/endpoints/chat.py`

### Module D – LLM Integration (Gemini)

- Nhiệm vụ:
  - Sinh câu trả lời Q&A
  - Tóm tắt text (PDF extracted)
  - Context window: gửi kèm N messages gần nhất
- Files:
  - `backend/app/services/llm_service.py`
  - `backend/app/core/config.py` (`GOOGLE_API_KEY`, `GEMINI_MODEL`, `CHAT_CONTEXT_WINDOW`)

### Module E – Scientific Tools

- Nhiệm vụ:
  - Verify citation
  - Journal match
  - Retraction scan
  - AI writing detection
  - Summarize PDF (dựa trên extracted_text)
- Tương tác:
  - API Tools -> Tool engine -> Persist vào `chat_messages` với `message_type` + `tool_results`
- Files:
  - `backend/app/api/v1/endpoints/tools.py`
  - `backend/app/services/tools/*`

### Module F – Storage & File Handling (S3/Local)

- Nhiệm vụ:
  - Upload/Download, list files, stats
  - Encrypt file bytes trước khi lưu
  - PDF text extraction (PyMuPDF)
  - Pre-signed URL cho S3 (khi phù hợp)
- Files:
  - `backend/app/services/storage_service.py`
  - `backend/app/services/file_service.py`
  - `backend/app/api/v1/endpoints/upload.py`

### Module G – Admin Module

- Nhiệm vụ:
  - Overview/users/files/storage health
  - Admin delete any file
  - Audit logging cho hành động nhạy cảm
- Files:
  - `backend/app/api/v1/endpoints/admin.py`
  - `backend/app/schemas/admin.py`

### Module H – Crypto Layer

- Nhiệm vụ:
  - AES-256-GCM primitives
  - Key loading/generation
  - JSON/text encrypt/decrypt helpers
- Files:
  - `backend/app/core/crypto.py`
  - `backend/app/core/encrypted_types.py`

### Module I – Security/Pentest Toolkit

- Nhiệm vụ:
  - Quick audit script non-destructive
  - Reports + remediation matrix
- Files:
  - `backend/security/pentest/quick_audit.py`
  - `backend/security/reports/*`

### Module J – Frontend UI (Bohrium-like)

- Nhiệm vụ:
  - Landing page, login/register
  - Workspace: sidebar sessions + chat + tools/files panel
  - Admin dashboard UI
  - Typed API client + in-memory auth store
- Files:
  - `frontend/app/*`, `frontend/components/*`, `frontend/lib/*`

## 6) Luồng dữ liệu (data flow)

### 6.1 Auth flow

1. User `POST /api/v1/auth/register` -> DB insert `users`.
2. User `POST /api/v1/auth/login` -> JWT -> frontend giữ token in-memory.
3. Frontend gọi `GET /api/v1/auth/me` để lấy profile/role.

### 6.2 Chat flow (General Q&A)

1. Frontend tạo session `POST /api/v1/sessions`.
2. User gửi message `POST /api/v1/chat/{session_id}`.
3. Backend:
  - ABAC check ownership session.
  - Lưu user message vào `chat_messages` (encrypted content).
  - Load context N messages gần nhất.
  - (Optional) kèm snippet extracted_text từ file gần nhất nếu user hỏi “PDF/file/...”.
  - Gọi Gemini (nếu config hợp lệ) hoặc trả fallback text.
  - Lưu assistant message vào `chat_messages`.
4. Frontend poll messages `GET /api/v1/sessions/{session_id}/messages`.

### 6.3 Tool flow

1. Frontend gọi một tool endpoint (verify/journal/retract/ai-detect/summarize).
2. Backend chạy tool, tạo `tool_results` có cấu trúc + `message_type`.
3. Persist vào messages để hiển thị trong hội thoại.

### 6.4 Upload flow

1. Frontend `POST /api/v1/upload` (multipart).
2. Backend:
  - ABAC check session.
  - Validate MIME/size + PDF magic bytes.
  - Encrypt file bytes AES-256-GCM và upload S3/local.
  - Extract PDF text -> lưu encrypted vào DB (`file_attachments.extracted_text`).
  - Log một system message `message_type=file_upload`.
3. Frontend list `GET /api/v1/upload?session_id=...` và download `GET /api/v1/upload/{file_id}` (decrypt server-side).

## 7) API nodes (endpoints)

Tổng số endpoint backend:

- 33 endpoints dưới `/api/v1/*`
- + 1 endpoint `/health`
- Tổng cộng: **34** API nodes

### Auth (4)

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/admin/promote`

### Sessions (6)

- `POST /api/v1/sessions`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `PATCH /api/v1/sessions/{session_id}`
- `DELETE /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/messages`

### Chat (3)

- `POST /api/v1/chat/{session_id}`
- `POST /api/v1/chat/completions`
- `POST /api/v1/chat/completions/encrypted`

### Tools (6)

- `POST /api/v1/tools/verify-citation`
- `POST /api/v1/tools/journal-match`
- `POST /api/v1/tools/retraction-scan`
- `POST /api/v1/tools/summarize-pdf`
- `POST /api/v1/tools/detect-ai-writing`
- `POST /api/v1/tools/ai-detect` (alias)

### Upload (8)

- `POST /api/v1/upload`
- `GET /api/v1/upload`
- `GET /api/v1/upload/stats/me`
- `GET /api/v1/upload/stats/storage` (admin)
- `GET /api/v1/upload/{file_id}`
- `DELETE /api/v1/upload/{file_id}`
- `POST /api/v1/upload/presigned-upload` (S3 only)
- `GET /api/v1/upload/{file_id}/presigned-download` (S3 only, non-encrypted)

### Admin (6)

- `GET /api/v1/admin/overview`
- `GET /api/v1/admin/users`
- `GET /api/v1/admin/files`
- `DELETE /api/v1/admin/files/{file_id}`
- `GET /api/v1/admin/storage`
- `GET /api/v1/admin/storage/health`

### Health (1)

- `GET /health`

## 8) Backlog phát triển (hướng chuyển tiếp)

- Database migrations: Alembic + schema versioning.
- Rate limiting production-ready: Redis-based limiter, per-user buckets.
- Streaming chat: SSE/WebSocket (frontend + backend).
- Vector DB thật cho journal recommendations (Qdrant/PGVector).
- Key rotation + re-encryption job (KMS/Vault integration).
- Observability: structured logs, tracing, metrics, alerting.

