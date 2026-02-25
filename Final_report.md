# 📝 AIRA — Final Report

## Môn: NT208 — Lập trình Ứng dụng Web
**Đề tài**: AIRA — Academic Integrity & Research Assistant  
**Mô tả**: Nền tảng web hỗ trợ nghiên cứu khoa học tích hợp AI, cung cấp các công cụ kiểm tra trích dẫn, gợi ý tạp chí, phát hiện retraction, và phát hiện văn bản AI trong một giao diện chat thống nhất.

---

# PHẦN I — Người dùng & Phân tích Nhu cầu (Use-cases)

## 1.1 Phân loại Nhóm Người dùng

| Nhóm | Role trong hệ thống | Mô tả |
|------|---------------------|-------|
| **Nhà nghiên cứu (Researcher)** | `RESEARCHER` | Sinh viên cao học, nghiên cứu sinh, giảng viên — người viết và nộp bài báo khoa học. Đây là nhóm người dùng chính. |
| **Quản trị viên (Admin)** | `ADMIN` | Quản lý hệ thống, giám sát người dùng, quản lý storage và theo dõi audit log. |

## 1.2 Nhu cầu & Use-cases Chi tiết

### 1.2.1 Nhà nghiên cứu (Researcher)

| # | Use-case | Mô tả chi tiết | Endpoint liên quan |
|---|----------|-----------------|-------------------|
| UC-01 | **Đăng ký / Đăng nhập** | Tạo tài khoản mới hoặc đăng nhập bằng email + password. JWT token được cấp phát (1h TTL). | `POST /auth/register`, `POST /auth/login` |
| UC-02 | **Chat AI tổng hợp (General Q&A)** | Hỏi đáp về nghiên cứu khoa học với Google Gemini AI. Hệ thống tự động tạo session, lưu lịch sử, duy trì context window 8 tin nhắn. | `POST /chat/completions` |
| UC-03 | **Kiểm tra trích dẫn (Citation Verification)** | Dán đoạn text chứa trích dẫn → hệ thống trích xuất citations (APA, IEEE, Vancouver, DOI) → xác minh qua OpenAlex + Crossref → phát hiện trích dẫn ảo (hallucinated). | `POST /tools/verify-citation` |
| UC-04 | **Gợi ý tạp chí (Journal Matching)** | Dán abstract bài báo → hệ thống phân tích lĩnh vực, tính similarity bằng SPECTER2/SciBERT embeddings → gợi ý top 5 tạp chí phù hợp với impact factor. | `POST /tools/journal-match` |
| UC-05 | **Quét retraction (Retraction Scan)** | Dán text chứa DOI → hệ thống kiểm tra Crossref `update-to`, OpenAlex `is_retracted`, PubPeer feedback → cảnh báo mức rủi ro (NONE → CRITICAL). | `POST /tools/retraction-scan` |
| UC-06 | **Phát hiện văn bản AI (AI Writing Detection)** | Dán đoạn text → RoBERTa GPT-2 detector (ML 70%) + rule-based heuristics (30%) → ensemble score + verdict (LIKELY_HUMAN / UNCERTAIN / LIKELY_AI). | `POST /tools/detect-ai-writing` |
| UC-07 | **Tóm tắt PDF** | Upload file PDF → PyMuPDF extract text → Google Gemini tóm tắt thành tiếng Việt (~180 từ). | `POST /tools/summarize-pdf` |
| UC-08 | **Upload & quản lý file** | Upload PDF/DOC/image → mã hóa AES-256-GCM → lưu trữ local/S3. Tự động extract text cho PDF để phục vụ file context khi chat. | `POST /upload`, `GET /upload`, `DELETE /upload/{id}` |
| UC-09 | **Quản lý session** | Tạo/đổi tên/xóa session. Chuyển mode (General Q&A ↔ Verification ↔ Journal Match). | `POST/GET/PATCH/DELETE /sessions` |
| UC-10 | **Xem lịch sử chat** | Xem lại tin nhắn cũ theo session, bao gồm kết quả tool (bảng citation, journal list, retraction report). | `GET /sessions/{id}/messages` |
| UC-11 | **Download file** | Tải file đã upload về, tự động giải mã AES-256-GCM. | `GET /upload/{file_id}` |

### 1.2.2 Quản trị viên (Admin)

| # | Use-case | Mô tả chi tiết | Endpoint liên quan |
|---|----------|-----------------|-------------------|
| UC-12 | **Dashboard tổng quan** | Xem thống kê: tổng users, sessions, messages, files, storage usage. Auto-refresh 15s. | `GET /admin/overview` |
| UC-13 | **Quản lý người dùng** | Xem danh sách users (phân trang), promote role. | `GET /admin/users`, `POST /auth/admin/promote` |
| UC-14 | **Quản lý files** | Xem/xóa tất cả files trong hệ thống, filter theo user/session. | `GET /admin/files`, `DELETE /admin/files/{id}` |
| UC-15 | **Giám sát storage** | Xem trạng thái storage backend (S3/Local), dung lượng, health check. | `GET /admin/storage` |

### Use-case Diagram

```
                          ┌─────────────────────────────────────┐
                          │           AIRA System               │
                          │                                     │
    ┌──────────┐         │  ┌──────────────────────────┐       │
    │Researcher│─────────┼──│ UC-01: Đăng ký/Đăng nhập │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-02: Chat AI (Q&A)     │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-03: Kiểm tra trích dẫn│       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-04: Gợi ý tạp chí    │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-05: Quét retraction   │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-06: Phát hiện AI text │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-07: Tóm tắt PDF      │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-08: Upload file       │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-09: Quản lý session   │       │
    │          │         │  ├──────────────────────────┤       │
    │          │─────────┼──│ UC-10: Xem lịch sử      │       │
    └──────────┘         │  ├──────────────────────────┤       │
                          │  │ UC-11: Download file     │       │
    ┌──────────┐         │  ├══════════════════════════┤       │
    │  Admin   │─────────┼──│ UC-12: Dashboard         │       │
    │          │─────────┼──│ UC-13: Quản lý users     │       │
    │          │─────────┼──│ UC-14: Quản lý files     │       │
    │          │─────────┼──│ UC-15: Giám sát storage  │       │
    └──────────┘         │  └──────────────────────────┘       │
         │                │                                     │
         │ «inherits»     └─────────────────────────────────────┘
         ▼
    ┌──────────┐
    │Researcher│  (Admin kế thừa toàn bộ use-case của Researcher)
    └──────────┘
```

## 1.3 Tính năng Giữ chân Người dùng (Retention)

| Tính năng "đinh" | Mô tả | Lý do giữ chân |
|-------------------|-------|-----------------|
| **Lịch sử chat persistent** | Mọi cuộc trò chuyện và kết quả tool được lưu vĩnh viễn, encrypted at-rest. | Researcher quay lại xem lại kết quả verify citation, journal gợi ý đã dùng trước đó — không cần chạy lại. |
| **All-in-one research hub** | 6 công cụ chuyên ngành + AI chat trong cùng 1 giao diện ChatGPT-like. | Thay vì dùng 5-6 trang web riêng lẻ (OpenAlex, Scimago, GPTZero, Gemini...), AIRA gộp tất cả. |
| **Auto file context** | Upload PDF → AI tự động đọc nội dung khi user hỏi "tóm tắt file" hoặc "summarize". | Workflow liền mạch: upload → hỏi → nhận câu trả lời dựa trên file. |
| **Multi-mode chat** | Chuyển mode (Q&A ↔ Verification ↔ Journal Match) ngay trong cùng 1 session. | Không cần ra trang khác, giảm friction, tăng tần suất sử dụng. |
| **Dark mode + responsive** | Giao diện hiện đại, hỗ trợ dark/light mode theo system preference. | Trải nghiệm thoải mái khi làm việc lâu dài ban đêm — nhóm đối tượng PhD/PhD candidate thường làm khuya. |

---

# PHẦN II — Phân tích Cạnh tranh & Chiến lược Khác biệt

## 2.1 Đối thủ Cạnh tranh

| Đối thủ | Loại | Tính năng chính | Giá | Hạn chế so với AIRA |
|---------|------|-----------------|-----|---------------------|
| **ChatGPT / Gemini** (trực tiếp) | Gián tiếp | Chat AI tổng hợp | Free → $20/mo | Không có citation verification, journal matching, retraction scan tích hợp. Không lưu structured tool results. |
| **Scimago Journal Rank** | Gián tiếp | Xếp hạng tạp chí | Free | Chỉ browse danh sách — không phân tích abstract tự động, không gợi ý dựa trên nội dung bài. |
| **OpenAlex** | Gián tiếp | Metadata học thuật | Free API | API thô, không có UI chat-based, phải tự viết code. |
| **GPTZero / Turnitin AI** | Gián tiếp | Phát hiện AI text | $10-25/mo | Chỉ 1 tính năng, không tích hợp research tools khác. |
| **Retraction Watch** | Gián tiếp | Danh sách retraction | Free blog | Không có API check tự động, phải search thủ công. |
| **Consensus.app** | Trực tiếp | AI search bài báo | $6.99/mo | Tập trung search, không có verify/retraction/AI detect tích hợp. |

**Kết luận**: Không có đối thủ trực tiếp nào cung cấp **tất cả 6 công cụ** trong 1 giao diện chat.

## 2.2 Lợi thế Cạnh tranh

| Lợi thế | Chi tiết |
|---------|---------|
| **All-in-one** | 6 công cụ (chat AI + citation check + journal match + retraction scan + AI detection + PDF summary) trong 1 UI duy nhất. |
| **Free & Self-hosted** | Open-source, deploy trên server riêng — không phụ thuộc SaaS, không giới hạn queries/tháng. |
| **ML-enhanced** | SPECTER2/SciBERT embeddings cho journal matching (không chỉ keyword matching), RoBERTa ensemble cho AI detection. |
| **End-to-end Encryption** | AES-256-GCM tại database level (EncryptedText/EncryptedJSON) + file encryption — bảo vệ dữ liệu nghiên cứu nhạy cảm. |
| **Vietnamese-first** | UI/system prompt hỗ trợ tiếng Việt, phù hợp đối tượng sinh viên/giảng viên Việt Nam. |

## 2.3 Chống Sao chép

| Rào cản | Mô tả |
|---------|-------|
| **ML Pipeline phức tạp** | Tích hợp SPECTER2 + SciBERT + RoBERTa + TF-IDF fallback chain với graceful degradation — không phải plug-and-play. |
| **Multi-source data integration** | Kết hợp OpenAlex + Crossref + PubPeer + Habanero — cần hiểu API schema của từng nguồn. |
| **5-layer encryption** | Kiến trúc bảo mật 5 lớp (transit → JWT → at-rest DB → file → optional client-side) — cần kiến thức cryptography chuyên sâu. |
| **Domain knowledge** | 35+ journals database với domain classification, impact factor, citation patterns chuyên ngành — cần kiến thức xuất bản học thuật. |

## 2.4 Unique Selling Proposition (USP)

> **AIRA là nền tảng duy nhất kết hợp AI chatbot + citation verification + journal recommendation + retraction scanning + AI writing detection trong một giao diện chat thống nhất, với mã hóa end-to-end và hoàn toàn miễn phí.**

Cụ thể:
- **Chưa có trang web nào** cho phép user chat AI → chuyển mode sang "Verification" → dán text → nhận bảng citation report → ngay lập tức chuyển sang "Journal Match" → nhận gợi ý tạp chí — tất cả trong cùng 1 session, cùng 1 giao diện.
- **Encrypted research data**: Không một chatbot AI nào hiện tại mã hóa AES-256-GCM cả database lẫn file upload.

---

# PHẦN III — Sơ đồ Kiến trúc Hệ thống

## 3.1 System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT (Browser)                             │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Next.js 15 + React 18 + TypeScript + Tailwind CSS v4       │    │
│  │                                                              │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │    │
│  │  │ Landing  │ │  Login/  │ │   Chat   │ │  Admin   │       │    │
│  │  │  Page    │ │ Register │ │   View   │ │Dashboard │       │    │
│  │  └──────────┘ └──────────┘ └─────┬────┘ └──────────┘       │    │
│  │                                   │                          │    │
│  │  ┌───────────┐ ┌───────────┐ ┌───┴──────┐ ┌───────────┐    │    │
│  │  │ AuthCtx   │ │ ChatStore │ │ API lib  │ │ ThemeCtx  │    │    │
│  │  │  (JWT)    │ │(useReducer│ │(25 methods│ │(dark/light│    │    │
│  │  └───────────┘ └───────────┘ └────┬─────┘ └───────────┘    │    │
│  └───────────────────────────────────┼──────────────────────────┘    │
│                                       │ HTTP (fetch)                  │
└───────────────────────────────────────┼──────────────────────────────┘
                                        │
                    ════════════════════════════════════
                    │  HTTPS + CORS + CSP + HSTS      │
                    ════════════════════════════════════
                                        │
┌───────────────────────────────────────┼──────────────────────────────┐
│                     BACKEND (FastAPI + Python)                        │
│                                       │                               │
│  ┌────────────────────────────────────┼────────────────────────┐     │
│  │                    Middleware Stack                          │     │
│  │  SecurityHeadersMiddleware → RateLimitMiddleware → CORS    │     │
│  └────────────────────────────────────┬────────────────────────┘     │
│                                       │                               │
│  ┌────────────────────────────────────┼────────────────────────┐     │
│  │                  API Router (v1)                             │     │
│  │                                                             │     │
│  │  ┌──────┐ ┌──────────┐ ┌──────┐ ┌───────┐ ┌──────┐ ┌────┐│     │
│  │  │ auth │ │ sessions │ │ chat │ │ tools │ │upload│ │admin││     │
│  │  │(4ep) │ │  (6ep)   │ │(3ep) │ │ (6ep) │ │(7ep) │ │(7ep)│     │
│  │  └──┬───┘ └────┬─────┘ └──┬───┘ └──┬────┘ └──┬───┘ └─┬──┘│     │
│  └─────┼──────────┼──────────┼────────┼─────────┼───────┼────┘     │
│        │          │          │        │         │       │           │
│  ┌─────┼──────────┼──────────┼────────┼─────────┼───────┼────┐     │
│  │     ▼          ▼          ▼        ▼         ▼       ▼    │     │
│  │  ┌──────────────────────────────────────────────────────┐ │     │
│  │  │              Authorization Layer                     │ │     │
│  │  │   RBAC (Permission enum) + ABAC (ownership check)   │ │     │
│  │  └──────────────────────────────────────────────────────┘ │     │
│  │                                                           │     │
│  │  ┌─────────────┐ ┌─────────────┐ ┌──────────────────┐    │     │
│  │  │ ChatService │ │ FileService │ │  GeminiService   │    │     │
│  │  │ (mode route)│ │ (upload/dl) │ │  (LLM calls)     │    │     │
│  │  └──────┬──────┘ └──────┬──────┘ └────────┬─────────┘    │     │
│  │         │               │                  │              │     │
│  │  ┌──────┴──────────────────────────────────┘              │     │
│  │  │  ML Tool Modules                                       │     │
│  │  │  ┌─────────────┐ ┌──────────────┐ ┌───────────────┐   │     │
│  │  │  │JournalFinder│ │CitationCheck │ │RetractionScan │   │     │
│  │  │  │(SPECTER2/   │ │(PyAlex +     │ │(Crossref +    │   │     │
│  │  │  │ SciBERT)    │ │ Habanero)    │ │ PubPeer)      │   │     │
│  │  │  └─────────────┘ └──────────────┘ └───────────────┘   │     │
│  │  │  ┌─────────────┐                                      │     │
│  │  │  │AIWritingDet │                                      │     │
│  │  │  │(RoBERTa +   │                                      │     │
│  │  │  │ heuristics) │                                      │     │
│  │  │  └─────────────┘                                      │     │
│  │  └────────────────────────────────────────────────────────│     │
│  │                                                           │     │
│  │  ┌─────────────────────────────────────────────────────┐  │     │
│  │  │            Storage Service (Strategy Pattern)       │  │     │
│  │  │  ┌──────────────┐         ┌───────────────┐        │  │     │
│  │  │  │  S3Storage   │  ←OR→   │ LocalStorage  │        │  │     │
│  │  │  │  (boto3)     │         │ (filesystem)  │        │  │     │
│  │  │  └──────────────┘         └───────────────┘        │  │     │
│  │  │         ↕ AES-256-GCM encryption (CryptoManager)   │  │     │
│  │  └─────────────────────────────────────────────────────┘  │     │
│  └───────────────────────────────────────────────────────────┘     │
│                           │                                         │
│  ┌────────────────────────┼────────────────────────────────────┐   │
│  │              SQLAlchemy ORM + Encryption Layer              │   │
│  │  ┌──────┐ ┌───────────┐ ┌────────────┐ ┌────────────────┐  │   │
│  │  │ User │ │ChatSession│ │ChatMessage │ │FileAttachment  │  │   │
│  │  └──────┘ └───────────┘ │(EncryptedT)│ │(EncryptedText) │  │   │
│  │                          └────────────┘ └────────────────┘  │   │
│  └─────────────────────────────┼───────────────────────────────┘   │
│                                │                                     │
└────────────────────────────────┼─────────────────────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │   SQLite (dev)          │
                    │   PostgreSQL (prod)     │
                    └─────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │        External Services             │
                    │                                     │
                    │  ┌─────────────┐ ┌──────────────┐   │
                    │  │Google Gemini│ │  OpenAlex    │   │
                    │  │  (LLM API) │ │  (free API)  │   │
                    │  └─────────────┘ └──────────────┘   │
                    │  ┌─────────────┐ ┌──────────────┐   │
                    │  │  Crossref   │ │   PubPeer    │   │
                    │  │ (Habanero)  │ │  (REST API)  │   │
                    │  └─────────────┘ └──────────────┘   │
                    │  ┌─────────────┐                    │
                    │  │  AWS S3     │                    │
                    │  │ (optional)  │                    │
                    │  └─────────────┘                    │
                    └─────────────────────────────────────┘
```

## 3.2 Module chính & Chức năng

| Module | File(s) | Chức năng |
|--------|---------|-----------|
| **Auth** | `core/security.py`, `endpoints/auth.py` | Đăng ký, đăng nhập, JWT token (bcrypt + HS256), OAuth2 Bearer |
| **Authorization** | `core/authorization.py` | RBAC (6 permissions) + ABAC (ownership check), AccessGateway |
| **Chat** | `services/chat_service.py`, `endpoints/chat.py` | Mode-based routing (Q&A/Verification/Journal), context memory, file context injection |
| **Tools** | `services/tools/*.py`, `endpoints/tools.py` | 4 ML tool modules (journal, citation, retraction, AI detect), 6 API endpoints |
| **Storage** | `services/storage_service.py`, `endpoints/upload.py` | Dual-backend (S3/Local), AES-256-GCM encryption at-rest, presigned URLs |
| **Crypto** | `core/crypto.py`, `core/encrypted_types.py` | Master key management, transparent SQLAlchemy encryption |
| **Middleware** | `core/middleware.py`, `core/rate_limit.py` | Security headers (CSP, HSTS), fixed-window rate limiter |
| **Admin** | `endpoints/admin.py`, `services/bootstrap.py` | Dashboard stats, user/file management, auto admin bootstrap |
| **LLM** | `services/llm_service.py` | Google Gemini dual-SDK, chat response + PDF summarization |
| **Frontend** | `frontend/` (Next.js) | 7 routes, ChatGPT-style UI, React Query, dark mode, auth guard |

---

# PHẦN IV — Thiết kế Luồng dữ liệu & UML

## 4.1 Data Flow Diagram (DFD Level 0)

```
                    ┌──────────────────────────────────┐
                    │        External APIs              │
                    │  (Gemini, OpenAlex, Crossref,    │
                    │   PubPeer, S3)                    │
                    └────────────┬─────────────────────┘
                                 │ HTTP responses
                                 ▼
┌──────┐  1.Register/Login  ┌────────────┐  5.Tool results   ┌──────────┐
│      │ ─────────────────▶ │            │ ────────────────▶  │          │
│      │  2.Send message    │   AIRA     │  6.LLM response   │ Database │
│ User │ ─────────────────▶ │   Backend  │ ────────────────▶  │ (SQLite/ │
│      │  3.Upload file     │  (FastAPI) │  7.File stored     │ Postgres)│
│      │ ─────────────────▶ │            │ ────────────────▶  │          │
│      │  4.Request history │            │                    │          │
│      │ ─────────────────▶ │            │◀────────────────   │          │
│      │◀───────────────── │            │  8.Query results   │          │
│      │  responses         │            │                    │          │
└──────┘                    └────────────┘                    └──────────┘
                                 │ ▲
                                 │ │  File I/O (encrypted)
                                 ▼ │
                            ┌─────────┐
                            │ Storage │
                            │(Local/S3│
                            └─────────┘
```

## 4.2 DFD Level 1 — Luồng Chat chi tiết

```
User ──message──▶ [1.0 Authenticate] ──JWT valid──▶ [2.0 Route by Mode]
                                                          │
                          ┌───────────────────────────────┼───────────────┐
                          ▼                               ▼               ▼
                  [2.1 General Q&A]            [2.2 Verification]  [2.3 Journal Match]
                          │                               │               │
                          ▼                               ▼               ▼
                  [3.1 Build context]          [3.2 Extract citations]  [3.3 Analyze abstract]
                  [3.1a File context?]         [3.2a Verify via       [3.3a SPECTER2/SciBERT
                          │                    OpenAlex+Crossref]      embeddings]
                          ▼                               │               │
                  [4.1 Call Gemini]                       ▼               ▼
                          │                    [4.2 Build report]  [4.3 Rank journals]
                          ▼                               │               │
                  ┌───────┴───────────────────────────────┴───────────────┘
                  ▼
          [5.0 Save messages] ──▶ DB (encrypted via EncryptedText/EncryptedJSON)
                  │
                  ▼
          [6.0 Return response] ──▶ User (ChatCompletionResponse)
```

## 4.3 Sequence Diagram — Chat Completion Flow (UC-02)

```
┌──────┐      ┌─────────┐      ┌───────────┐     ┌───────────┐     ┌────┐
│Client│      │ FastAPI  │      │ChatService│     │GeminiServ │     │ DB │
└──┬───┘      └────┬────┘      └─────┬─────┘     └─────┬─────┘     └──┬─┘
   │               │                 │                  │              │
   │ POST /chat/completions         │                  │              │
   │ {session_id, user_message}     │                  │              │
   │──────────────▶│                 │                  │              │
   │               │ get_current_user()                │              │
   │               │─────────────────────────────────────────────────▶│
   │               │◀────────────────────────────────────────────────│
   │               │                 │                  │              │
   │               │ complete_chat() │                  │              │
   │               │────────────────▶│                  │              │
   │               │                 │ assert_session_access()        │
   │               │                 │─────────────────────────────▶ │
   │               │                 │◀───────────────────────────── │
   │               │                 │                  │              │
   │               │                 │ save user_msg    │              │
   │               │                 │─────────────────────────────▶ │
   │               │                 │                  │              │
   │               │                 │ _build_file_context()          │
   │               │                 │─────────────────────────────▶ │
   │               │                 │◀───────────────────────────── │
   │               │                 │                  │              │
   │               │                 │ generate_response()            │
   │               │                 │─────────────────▶│              │
   │               │                 │                  │──▶ Gemini API
   │               │                 │                  │◀── response
   │               │                 │◀────────────────│              │
   │               │                 │                  │              │
   │               │                 │ save assistant_msg              │
   │               │                 │─────────────────────────────▶ │
   │               │                 │                  │              │
   │               │◀───────────────│                  │              │
   │               │ ChatCompletionResponse             │              │
   │◀──────────────│                 │                  │              │
   │               │                 │                  │              │
```

## 4.4 Sequence Diagram — Citation Verification (UC-03)

```
┌──────┐     ┌────────┐     ┌───────────┐    ┌──────────────┐   ┌────────┐
│Client│     │FastAPI │     │ToolsEndpt │    │CitationCheck │   │External│
└──┬───┘     └───┬────┘     └─────┬─────┘    └──────┬───────┘   └───┬────┘
   │             │                │                  │               │
   │POST /tools/verify-citation   │                  │               │
   │────────────▶│                │                  │               │
   │             │────────────────▶│                  │               │
   │             │                │                  │               │
   │             │                │ citation_checker.verify(text)    │
   │             │                │─────────────────▶│               │
   │             │                │                  │               │
   │             │                │                  │extract_citations()
   │             │                │                  │  (6 regex patterns)
   │             │                │                  │               │
   │             │                │                  │ pyalex.Works.search()
   │             │                │                  │──────────────▶│ OpenAlex
   │             │                │                  │◀─────────────│
   │             │                │                  │               │
   │             │                │                  │ habanero.works(doi)
   │             │                │                  │──────────────▶│ Crossref
   │             │                │                  │◀─────────────│
   │             │                │                  │               │
   │             │                │                  │ _fuzzy_match_author()
   │             │                │                  │ _compute_confidence()
   │             │                │                  │               │
   │             │                │◀────────────────│ [CitationCheckResult]
   │             │                │                  │               │
   │             │                │ persist_tool_interaction()       │
   │             │                │  (save to chat DB)               │
   │             │                │                  │               │
   │             │◀───────────────│                  │               │
   │◀────────────│ CitationVerifyResponse            │               │
   │             │                │                  │               │
```

---

# PHẦN V — Thiết kế Cơ sở Dữ liệu

## 5.1 Entity-Relationship Diagram (ERD)

```
┌──────────────────────────┐
│          users           │
├──────────────────────────┤
│ PK  id          VARCHAR(36)│     ┌──────────────────────────────┐
│     email       VARCHAR(255)│     │       chat_sessions          │
│     full_name   VARCHAR(255)│     ├──────────────────────────────┤
│     hashed_pw   VARCHAR(255)│     │ PK  id          VARCHAR(36) │
│     role        ENUM        │     │ FK  user_id     VARCHAR(36) │──┐
│     created_at  DATETIME(tz)│     │     title       VARCHAR(255)│  │
└────────────┬───────────────┘     │     mode        ENUM        │  │
             │                      │     created_at  DATETIME(tz)│  │
             │ 1:N                  │     updated_at  DATETIME(tz)│  │
             └──────────────────────┤                              │  │
                                    └──────────┬───────────────────┘  │
                                               │                      │
                              1:N              │             1:N      │
                    ┌──────────────────────────┘                      │
                    │                                                  │
                    ▼                                                  │
┌──────────────────────────────────┐                                  │
│         chat_messages            │                                  │
├──────────────────────────────────┤                                  │
│ PK  id            VARCHAR(36)   │                                  │
│ FK  session_id    VARCHAR(36)   │──┘                               │
│     role          ENUM          │                                   │
│     message_type  ENUM          │      ┌────────────────────────────┤
│     content       ENCRYPTED_TEXT│      │                            │
│     tool_results  ENCRYPTED_JSON│      │                            │
│     created_at    DATETIME(tz)  │      │                            │
└──────────┬───────────────────────┘      │                            │
           │                              │                            │
           │ 1:N                          │                            │
           ▼                              │                            │
┌──────────────────────────────────┐      │                            │
│       file_attachments           │      │                            │
├──────────────────────────────────┤      │                            │
│ PK  id               VARCHAR(36)│      │                            │
│ FK  session_id       VARCHAR(36)│──────┘  (FK → chat_sessions)     │
│ FK  message_id       VARCHAR(36)│  (FK → chat_messages, nullable)  │
│ FK  user_id          VARCHAR(36)│─────────┘  (FK → users)          │
│     file_name        VARCHAR(255)│                                  │
│     mime_type        VARCHAR(128)│                                  │
│     size_bytes       BIGINT     │                                  │
│     storage_key      ENCRYPTED  │                                  │
│     storage_url      ENCRYPTED  │                                  │
│     storage_encrypted BOOLEAN   │                                  │
│     storage_enc_alg  VARCHAR(64)│                                  │
│     extracted_text   ENCRYPTED  │                                  │
│     created_at       DATETIME(tz│                                  │
└──────────────────────────────────┘                                  │
```

## 5.2 Mối quan hệ

| Quan hệ | Loại | Chi tiết |
|---------|------|---------|
| `users` → `chat_sessions` | 1:N | Mỗi user có nhiều session. `CASCADE DELETE` khi xóa user. |
| `chat_sessions` → `chat_messages` | 1:N | Mỗi session có nhiều message. `CASCADE DELETE` khi xóa session. |
| `chat_messages` → `file_attachments` | 1:N | Mỗi message có thể có nhiều file. `SET NULL` khi xóa message. |
| `chat_sessions` → `file_attachments` | 1:N | File thuộc session. `CASCADE DELETE` khi xóa session. |
| `users` → `file_attachments` | 1:N | File thuộc user. `CASCADE DELETE` khi xóa user. |

## 5.3 Indexes

| Table | Index | Columns | Mục đích |
|-------|-------|---------|----------|
| `users` | `ix_users_email` (unique) | `email` | Login lookup |
| `chat_sessions` | `ix_sessions_user_id` | `user_id` | List sessions by user |
| `chat_messages` | `ix_chatmsg_session_created` | `(session_id, created_at)` | List messages in order |
| `file_attachments` | `ix_fileatt_session_created` | `(session_id, created_at)` | List files in session |
| `file_attachments` | `ix_fileatt_user_created` | `(user_id, created_at)` | User file listing |

## 5.4 Encryption tại Database Level

| Column | Type | Encryption |
|--------|------|-----------|
| `chat_messages.content` | `EncryptedText` | AES-256-GCM → base64 → Text column |
| `chat_messages.tool_results` | `EncryptedJSON` | JSON → AES-256-GCM → base64 → Text column |
| `file_attachments.storage_key` | `EncryptedText` | Path mã hóa |
| `file_attachments.storage_url` | `EncryptedText` | URL mã hóa |
| `file_attachments.extracted_text` | `EncryptedText` | Nội dung PDF đã extract mã hóa |

SQLAlchemy `TypeDecorator` tự động encrypt khi write và decrypt khi read — transparent đối với application code.

---

# PHẦN VI — Minimum Viable Product (MVP)

## 6.1 MVP Features đã hoàn thiện

| Feature | Status | Mô tả |
|---------|--------|-------|
| Đăng ký / Đăng nhập | ✅ Done | JWT auth, bcrypt password hashing |
| Chat AI (Gemini) | ✅ Done | Real-time Q&A, context memory 8 messages |
| Citation Verification | ✅ Done | 6 citation patterns, OpenAlex + Crossref verification |
| Journal Matching | ✅ Done | 35 journals, SPECTER2/SciBERT similarity |
| Retraction Scan | ✅ Done | Crossref + OpenAlex + PubPeer, risk levels |
| AI Writing Detection | ✅ Done | RoBERTa ensemble + rule-based heuristics |
| PDF Summary | ✅ Done | PyMuPDF extract + Gemini summarize |
| File Upload/Download | ✅ Done | AES-256-GCM encrypted storage |
| Admin Dashboard | ✅ Done | Overview, users, files, storage management |
| Dark Mode | ✅ Done | System preference + manual toggle |
| Security Hardening | ✅ Done | 5-layer encryption, rate limiting, audit log |

## 6.2 Tech Stack & Lý do chọn

### Backend: Python + FastAPI

| Lý do | Chi tiết |
|-------|---------|
| **AI/ML ecosystem** | PyTorch, Transformers, Sentence-Transformers, scikit-learn — tất cả Python-native. Không thể dùng Node.js cho SPECTER2/RoBERTa. |
| **FastAPI performance** | Async-capable, auto-generated OpenAPI docs, Pydantic validation — nhanh nhất Python web framework. |
| **Google Gemini SDK** | `google-genai` Python SDK là first-class citizen, hỗ trợ đầy đủ nhất. |
| **Academic Python ecosystem** | PyAlex, Habanero, PyMuPDF — hầu hết academic tools đều Python. |

### Frontend: Next.js 15 + React 18

| Lý do | Chi tiết |
|-------|---------|
| **Server-side rendering** | SEO cho landing page, fast initial load. |
| **App Router** | File-based routing, layouts, loading states — giảm boilerplate. |
| **React ecosystem** | React Query (TanStack), Sonner, Lucide icons — mature ecosystem. |
| **TypeScript** | Type safety cho 25 API methods, 10 interfaces — giảm runtime errors. |
| **Tailwind CSS v4** | Utility-first, dark mode built-in, design token system với `@theme`. |

### Database: SQLAlchemy + SQLite/PostgreSQL

| Lý do | Chi tiết |
|-------|---------|
| **ORM + Raw SQL** | SQLAlchemy cho CRUD, `func.count/sum` cho aggregation — flexible. |
| **Transparent encryption** | Custom `TypeDecorator` cho AES-256-GCM — unique capability. |
| **SQLite → PostgreSQL** | Chuyển đổi bằng 1 biến môi trường `DATABASE_URL` — zero code change. |

### External APIs

| API | Mục đích | Tại sao chọn |
|-----|----------|-------------|
| **Google Gemini** | LLM cho chat + summarization | Free tier generous (60 requests/min), hỗ trợ Vietnamese, dual SDK. |
| **OpenAlex** | Metadata bài báo, DOI lookup | Free, open, 250M+ works — lớn nhất, không cần API key. |
| **Crossref** | Citation verification, retraction scan | Authoritative source cho DOI metadata, `update-to` field cho retraction. |
| **PubPeer** | Community feedback on papers | Unique source cho post-publication comments và concerns. |

## 6.3 Luồng MVP Core Demo

```
1. User mở AIRA → Landing page → Click "Get Started"
2. Đăng ký tài khoản mới (hoặc login)
3. Tự động chuyển đến /chat → Giao diện ChatGPT-style
4. Gõ câu hỏi nghiên cứu → Gemini trả lời → Lưu lịch sử
5. Chuyển mode sang "Verification" → Dán text có trích dẫn
6. Hệ thống hiện bảng Citation Report (status, DOI, confidence)
7. Chuyển mode "Journal Match" → Dán abstract
8. Hệ thống gợi ý top 5 tạp chí (tên, impact factor, similarity score)
9. Upload PDF → Hỏi "Tóm tắt file" → AI tóm tắt dựa trên nội dung PDF
10. Admin login → Dashboard thống kê → Quản lý users/files/storage
```

## 6.4 Giao diện UI

### Nguyên tắc thiết kế
- **ChatGPT-inspired**: Sidebar (session list) + Main area (messages) + Input area
- **Dark/Light mode**: System preference detection + manual toggle
- **Tailwind v4 design tokens**: `--color-accent`, `--color-bg-primary`, etc. — nhất quán toàn bộ
- **Responsive**: Desktop-first, sidebar collapsible trên mobile
- **Accessible**: Keyboard navigation (Enter to send, Shift+Enter newline)

### Các trang chính
| Route | Component | Chức năng |
|-------|-----------|-----------|
| `/` | `page.tsx` | Landing page — 4 feature cards, CTA buttons |
| `/login` | `login/page.tsx` | Tab Login/Register form, theme toggle |
| `/chat` | `chat/page.tsx` | ChatView — messages, mode selector, file upload |
| `/chat/[sessionId]` | `[sessionId]/page.tsx` | Load specific session |
| `/admin` | `admin/page.tsx` | Dashboard — overview, users, files, storage |

---

# PHẦN VII — Kế hoạch phát triển tiếp theo

## Giai đoạn 2 (Seminar #2)

| Tính năng | Mô tả | Ưu tiên |
|-----------|-------|---------|
| **Alembic migrations** | Schema versioning cho production database | 🔴 High |
| **Async refactor** | `async def` endpoints + `httpx.AsyncClient` — tăng throughput 3-5x | 🔴 High |
| **Token refresh flow** | Short-lived access token (15min) + refresh token (7 days) | 🔴 High |
| **Unit tests** | pytest (backend) + Jest (frontend) — target 80% coverage | 🟡 Medium |
| **Redis caching** | Cache tool results (citation check, retraction scan) — giảm external API calls | 🟡 Medium |

## Giai đoạn 3 (Seminar #3)

| Tính năng | Mô tả | Ưu tiên |
|-----------|-------|---------|
| **WebSocket real-time** | Streaming AI response (như ChatGPT), typing indicators | 🟡 Medium |
| **Vector DB (Qdrant)** | Semantic search across user's uploaded papers | 🟡 Medium |
| **Mobile responsive** | Hamburger menu, swipe gestures, PWA | 🟡 Medium |
| **i18n** | Full Vietnamese + English support | 🟢 Low |
| **Email notifications** | Confirmation, password reset, weekly research digest | 🟢 Low |
| **E2E tests** | Playwright test suite for all user flows | 🟢 Low |

---

# PHẦN VIII — Bố cục Slide Trình bày

## Slide đề xuất (10-12 slides)

| # | Slide | Nội dung | Thời gian |
|---|-------|---------|-----------|
| 1 | **Giới thiệu** | Tên đề tài, thành viên nhóm, vấn đề giải quyết (research integrity crisis) | 1 min |
| 2 | **Vấn đề** | Thống kê: 40K+ retracted papers, AI-generated text concerns, nhà nghiên cứu cần 5-6 tools riêng lẻ | 1 min |
| 3 | **Giải pháp** | AIRA = All-in-one Research Hub. Screenshot giao diện ChatGPT-style | 1 min |
| 4 | **Chân dung người dùng** | Researcher vs Admin, use-case diagram, retention features | 1.5 min |
| 5 | **USP & Cạnh tranh** | Bảng so sánh đối thủ, highlight "6 tools in 1 UI" + "encrypted" | 1 min |
| 6 | **Kiến trúc hệ thống** | System architecture diagram (đơn giản hóa), tech stack icons | 1.5 min |
| 7 | **Database ERD** | 4 bảng, quan hệ, encryption layers | 1 min |
| 8 | **Security** | 5-layer encryption diagram, RBAC + ABAC, audit log | 1 min |
| 9 | **Live Demo** | Chạy trực tiếp: register → chat → verify citation → journal match → upload PDF | **5 min** |
| 10 | **Kết quả & Thống kê** | 32/32 modules pass, 0 build errors, 38 security issues fixed, 28+ resolved | 1 min |
| 11 | **Roadmap** | Phase 2 + Phase 3 plans | 0.5 min |
| 12 | **Q&A** | | |

**Tổng**: ~15 min (5 min demo chiếm trọng tâm)

### Tips cho slide:
- Dùng **screenshots thật** từ AIRA (chat view, citation report table, admin dashboard)
- Mỗi slide **≤ 20 từ text** + 1 hình/diagram lớn
- Demo trực tiếp: chuẩn bị sẵn text mẫu có trích dẫn APA để verify
- Backup: quay video demo phòng trường hợp mạng lag
