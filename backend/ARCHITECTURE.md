# Kiến trúc Backend cho AIRA

## 1. Project Overview

- **Tên hệ thống**: `Academic Integrity & Research Assistant (AIRA)`
- **Mô tả**: Nền tảng hỗ trợ viết và nộp bài báo khoa học đến các tạp chí và hội nghị uy tín
- **Mô hình**: `Chat-based Web Application`
- **Phong cách kiến trúc**: `Modular Monolith + Layered Architecture`
- **Framework**: FastAPI + SQLAlchemy + Pydantic

### Luồng hoạt động chính
```
┌─────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────┐
│  User   │────▶│  FastAPI │────▶│   Service   │────▶│ Database │
│(Frontend)│    │  Router  │     │    Layer    │     │ (SQLite) │
└─────────┘     └──────────┘     └─────────────┘     └──────────┘
                     │                  │
                     │                  ▼
                     │           ┌─────────────┐
                     │           │  External   │
                     │           │   APIs      │
                     │           │ (Gemini,    │
                     │           │  OpenAlex,  │
                     │           │  Crossref)  │
                     │           └─────────────┘
                     ▼
              ┌─────────────┐
              │   Storage   │
              │ (S3/Local)  │
              └─────────────┘
```

### Quy trình người dùng
1. User đăng ký/đăng nhập → nhận JWT token
2. Tạo `Session` mới (new chat)
3. Chọn mode (`general_qa`, `verification`, `journal_match`)
4. Gửi message → Backend xử lý → Lưu lịch sử → Gọi LLM/Tool
5. Trả về response (text hoặc structured data)

## 2. Module chức năng

### Module 1: Chat Management
Quản lý hội thoại và lưu trữ context.

**Models:**
- `chat_sessions`: Quản lý danh sách đoạn chat cho sidebar
- `chat_messages`: Lưu đầy đủ user/assistant/tool output

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/sessions` | Tạo session mới |
| GET | `/api/v1/sessions` | Lấy danh sách sessions |
| GET | `/api/v1/sessions/{id}` | Chi tiết session |
| PATCH | `/api/v1/sessions/{id}` | Cập nhật session |
| DELETE | `/api/v1/sessions/{id}` | Xóa session |
| GET | `/api/v1/sessions/{id}/messages` | Lấy messages của session |
| POST | `/api/v1/chat/{session_id}` | Gửi tin nhắn |
| POST | `/api/v1/chat/completions` | OpenAI-compatible endpoint |

### Module 2: Intelligent Core (Gemini LLM)
Tích hợp AI để xử lý ngôn ngữ tự nhiên.

**Service:** `app/services/llm_service.py`

**Features:**
- Context window: Lấy N messages gần nhất (`CHAT_CONTEXT_WINDOW`, default 8)
- System prompt chuẩn hóa cho vai trò trợ lý nghiên cứu
- Tóm tắt PDF với text đã extract
- Auto-attach file context khi user hỏi về file

**Cấu hình:**
```python
model = "gemini-1.5-flash"
temperature = 0.7
max_output_tokens = 2048
```

### Module 3: Scientific Tools
Các công cụ chuyên biệt cho nghiên cứu khoa học.

#### 3.1 Citation Checker
Xác minh tính chính xác của trích dẫn.

| Version | Features |
|---------|----------|
| **V1** | OpenAlex API, basic pattern matching |
| **V2** | PyAlex + Habanero, multi-format parsing (APA/IEEE/Vancouver), confidence scoring, fuzzy author matching |

#### 3.2 Journal Finder
Gợi ý tạp chí phù hợp với bài báo.

| Version | Features |
|---------|----------|
| **V1** | 5 journals, keyword matching, TF-IDF similarity |
| **V2** | 35+ journals với metadata (h-index, acceptance rate, review time), SPECTER2/SciBERT embeddings, domain detection |

**Journals Database (V2):**
- Computer Science: IEEE TPAMI, ACM Computing Surveys, Nature Machine Intelligence...
- Biomedical: The Lancet, NEJM, Cell, Nature Medicine...
- Physics: Physical Review Letters, Nature Physics...
- Chemistry: JACS, Angewandte Chemie...
- Materials Science: Nature Materials, Advanced Materials...
- Environmental: Nature Climate Change, Environmental Science & Technology...
- Social Sciences: American Economic Review, Psychological Bulletin...

#### 3.3 Retraction Scanner
Kiểm tra bài báo đã bị rút hay chưa.

| Version | Features |
|---------|----------|
| **V1** | OpenAlex `is_retracted` + PubPeer comments |
| **V2** | Crossref `update-to` field, risk levels (NONE/LOW/MEDIUM/HIGH/CRITICAL), detailed metadata |

#### 3.4 AI Writing Detector
Phát hiện văn bản được tạo bởi AI.

| Version | Features |
|---------|----------|
| **V1** | Rule-based heuristics (TTR, sentence uniformity, pattern matching) |
| **V2** | RoBERTa GPT-2 detector, ensemble ML + rule-based, 25+ AI patterns, chunk analysis |

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tools/verify-citation` | Xác minh trích dẫn |
| POST | `/api/v1/tools/journal-match` | Gợi ý tạp chí |
| POST | `/api/v1/tools/retraction-scan` | Quét bài bị rút |
| POST | `/api/v1/tools/summarize-pdf` | Tóm tắt PDF |
| POST | `/api/v1/tools/ai-detect` | Phát hiện AI writing |

### Module 4: Storage & File Handling
Upload và xử lý file.

**Service:** `app/services/file_service.py`

**Features:**
- Upload: `POST /api/v1/upload`
- Download: `GET /api/v1/upload/{file_id}`
- Storage: S3 (primary) hoặc local fallback
- PDF parsing: PyMuPDF text extraction
- Encryption: AES-256-GCM trước khi ghi
- Metadata: Lưu vào `file_attachments` table

**File Flow:**
```
Upload → Validate → Extract Text → Encrypt → Store → Save Metadata
Download → Auth Check → Fetch → Decrypt → Return
```

### Module 5: Authentication & Authorization

**Authentication:**
- JWT tokens (python-jose)
- Password hashing (bcrypt)
- OAuth2PasswordBearer flow

**Authorization:**
- RBAC: `admin` vs `researcher` roles
- ABAC: Ownership-based access control
- Functions:
  - `assert_session_access()`
  - `assert_message_access()`
  - `assert_file_access()`

### Module 6: Admin Interface

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/admin/overview` | Dashboard stats |
| GET | `/api/v1/admin/users` | User management |
| POST | `/api/v1/auth/admin/promote` | Change user role |

**Bootstrap:**
- Auto-create admin on startup từ env vars
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`

## 3. Database Schema

### ERD Overview
```
users ──────────┬──────────── chat_sessions
                │                   │
                │                   │
                └───── file_attachments ─────┘
                              │
                              │
                       chat_messages
```

### Tables

#### users
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| email | String | Unique, indexed |
| hashed_password | String | Bcrypt hash |
| role | Enum | admin/researcher |
| created_at | DateTime | Auto timestamp |

#### chat_sessions
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| title | String | Session title |
| mode | Enum | general_qa/verification/journal_match |
| created_at | DateTime | Auto timestamp |
| updated_at | DateTime | Auto update |

#### chat_messages
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK → chat_sessions |
| role | Enum | user/assistant/system |
| message_type | Enum | text/file_upload/tool_result |
| content | EncryptedText | Message content (encrypted) |
| tool_results | EncryptedJSON | Tool output (encrypted) |
| created_at | DateTime | Auto timestamp |

#### file_attachments
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK → chat_sessions |
| message_id | UUID | FK → chat_messages |
| user_id | UUID | FK → users |
| file_name | String | Original filename |
| mime_type | String | MIME type |
| size_bytes | Integer | File size |
| storage_key | EncryptedText | S3/local key |
| storage_url | EncryptedText | Access URL |
| storage_encrypted | Boolean | File encryption flag |
| storage_encryption_alg | String | Encryption algorithm |
| extracted_text | EncryptedText | PDF text content |
| created_at | DateTime | Auto timestamp |

## 4. External Integrations

### Google Gemini
- **Purpose**: LLM for Q&A, summarization
- **Model**: gemini-1.5-flash
- **SDK**: google-generativeai (deprecated, migration needed)

### OpenAlex
- **Purpose**: Citation verification, retraction checking
- **Wrapper**: pyalex (V2)
- **Free tier**: Polite pool with email

### Crossref
- **Purpose**: DOI resolution, retraction status
- **Wrapper**: habanero (V2)
- **Field**: `update-to` for retraction info

### PubPeer
- **Purpose**: Post-publication peer review
- **API**: Direct HTTP calls
- **Data**: Comments and concerns

### Sentence Transformers
- **Purpose**: Scientific paper embeddings
- **Models**: SPECTER2, SciBERT
- **Fallback**: TF-IDF vectorization

## 5. Deployment Architecture

### Development
```bash
uvicorn app.main:app --reload
```

### Production (Recommended)
```
                    ┌─────────────┐
                    │   Nginx     │
                    │  (TLS/SSL)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
        │  Uvicorn  │ │ Uvicorn │ │  Uvicorn  │
        │  Worker 1 │ │ Worker 2│ │  Worker 3 │
        └─────┬─────┘ └────┬────┘ └─────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │  PostgreSQL │
                    │   + Redis   │
                    └─────────────┘
```

### Environment Variables
Xem [README.md](README.md#biến-môi-trường) để biết đầy đủ danh sách.

## 6. Hướng mở rộng

### Phase 1: Stability
- [ ] Alembic migrations
- [ ] Unit tests coverage > 80%
- [ ] Rate limiting
- [ ] Logging/monitoring

### Phase 2: Performance
- [ ] Redis cache cho session context
- [ ] Background job queue (Celery)
- [ ] Database connection pooling
- [ ] CDN cho static files

### Phase 3: Features
- [ ] WebSocket real-time chat
- [ ] Vector DB (Qdrant) cho recommendations
- [ ] Multi-language support
- [ ] Mobile API optimization

### Phase 4: Enterprise
- [ ] SSO/SAML integration
- [ ] Audit logging
- [ ] Key rotation automation
- [ ] Multi-tenant support
