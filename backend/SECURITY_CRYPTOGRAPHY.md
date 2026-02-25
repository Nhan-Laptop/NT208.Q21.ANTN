# Phân tích Cryptography & Authorization cho AIRA

## 1. Tổng quan bảo mật

### Mục tiêu
- **Confidentiality**: Bảo vệ dữ liệu nhạy cảm (messages, files, credentials)
- **Integrity**: Đảm bảo dữ liệu không bị thay đổi trái phép
- **Availability**: Hệ thống hoạt động ổn định và có khả năng phục hồi
- **Non-repudiation**: Audit trail cho các hành động quan trọng

### Security Layers
```
┌─────────────────────────────────────────────────────────┐
│                    HTTPS/TLS (Layer 7)                  │
├─────────────────────────────────────────────────────────┤
│               App-layer AES-256-GCM (Optional)          │
├─────────────────────────────────────────────────────────┤
│                 JWT Authentication                       │
├─────────────────────────────────────────────────────────┤
│               RBAC + ABAC Authorization                  │
├─────────────────────────────────────────────────────────┤
│              At-rest Encryption (Database)               │
├─────────────────────────────────────────────────────────┤
│              File Encryption (S3/Local)                  │
└─────────────────────────────────────────────────────────┘
```

## 2. Authentication

### JWT Token Flow
```
┌────────┐    credentials     ┌─────────┐
│ Client │ ─────────────────▶ │ /login  │
└────────┘                    └────┬────┘
     ▲                             │
     │     JWT access token        │ verify password
     └─────────────────────────────┤
                                   ▼
                            ┌─────────────┐
                            │   Database  │
                            │ (bcrypt pw) │
                            └─────────────┘
```

**Implementation:**
- Library: `python-jose[cryptography]`
- Algorithm: HS256 (HMAC-SHA256)
- Token lifetime: 30 minutes (configurable)
- Password hashing: bcrypt với auto-salt

**Code location:** `app/core/security.py`
```python
# Token creation
def create_access_token(data: dict, expires_delta: timedelta | None = None)

# Password verification  
def verify_password(plain_password: str, hashed_password: str) -> bool
```

### Khuyến nghị Production
1. Migrate sang RS256 (asymmetric) nếu có microservices
2. Implement refresh token flow
3. Token blacklist cho logout
4. Rate limit cho /login endpoint

## 3. In-transit Encryption: AES-256-GCM (Optional)

### Mục đích
Bổ sung thêm lớp bảo mật payload ở application layer, độc lập với TLS.

### Endpoint
```
POST /api/v1/chat/completions/encrypted
```

### Request Format
```json
{
  "payload": "<base64(nonce || tag || ciphertext)>"
}
```

### Encryption Flow
```
Client                                          Server
  │                                                │
  │  1. Generate nonce (12 bytes)                  │
  │  2. AES-GCM encrypt(plaintext, key, nonce)     │
  │  3. payload = base64(nonce + tag + ciphertext) │
  │                                                │
  │ ─────────────── POST payload ─────────────────▶│
  │                                                │
  │                 4. base64 decode               │
  │                 5. Extract nonce, tag, ct      │
  │                 6. AES-GCM decrypt             │
  │                 7. Process request             │
  │                 8. Encrypt response            │
  │                                                │
  │◀──────────── Encrypted response ──────────────│
```

### AAD (Additional Authenticated Data)
- User ID được dùng làm AAD
- Ràng buộc payload với identity người gửi
- Ngăn chặn replay attack

### Lưu ý
> ⚠️ AES app-layer **không thay thế** TLS. Đây là defense-in-depth.
> Bắt buộc vẫn phải deploy với HTTPS.

## 4. At-rest Encryption: AES-256-GCM

### Triển khai
Dùng SQLAlchemy custom types để tự động encrypt/decrypt.

**Code location:** `app/core/encrypted_types.py`
```python
class EncryptedText(TypeDecorator)    # Cho String fields
class EncryptedJSON(TypeDecorator)    # Cho JSON fields
```

### Các trường được mã hóa

| Table | Field | Type |
|-------|-------|------|
| chat_messages | content | EncryptedText |
| chat_messages | tool_results | EncryptedJSON |
| file_attachments | storage_key | EncryptedText |
| file_attachments | storage_url | EncryptedText |
| file_attachments | extracted_text | EncryptedText |

### Encryption Format
```
┌──────────┬──────────┬─────────────────┐
│  Nonce   │   Tag    │   Ciphertext    │
│ 12 bytes │ 16 bytes │   Variable      │
└──────────┴──────────┴─────────────────┘
         ▼
    base64 encode
         ▼
   Store in DB
```

### File Encryption
Files được mã hóa trước khi lưu vào S3 hoặc local storage.

```python
# app/services/file_service.py
def _encrypt_file_data(data: bytes) -> bytes:
    """AES-256-GCM encrypt file content."""
```

Với S3, backend còn bật thêm `ServerSideEncryption=AES256` (double encryption).

### Ưu điểm
- Bảo vệ dữ liệu ngay cả khi DB dump bị lộ
- Không phụ thuộc vào tính năng encryption của DB engine
- Portable giữa các database backends

### Hạn chế
- Không thể search/index trên trường encrypted
- Cần re-encrypt toàn bộ data khi rotate key
- Performance overhead ~5-10%

## 5. Key Management

### Key Sources (theo thứ tự ưu tiên)

1. **Environment variable**: `ADMIN_MASTER_KEY_B64`
   ```bash
   # Generate key
   python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
   ```

2. **Key file**: `.aira_master_key`
   - Auto-generated nếu không có env var
   - Stored locally (chỉ cho development)

### Key Generation Script
```bash
python scripts/generate_keys.py
```

Output:
```
========================================
AIRA Security Keys Generator
========================================

1. ADMIN_MASTER_KEY_B64 (AES-256 encryption):
   KqL8x9+...==

2. JWT_SECRET_KEY (Token signing):  
   a7f3b2c...

3. Suggested ADMIN_PASSWORD:
   Xk9$mN2...
```

### Production Recommendations

| Aspect | Development | Production |
|--------|-------------|------------|
| Key storage | File/env var | AWS KMS / HashiCorp Vault |
| Key rotation | Manual | Automated (quarterly) |
| Key backup | Local | Encrypted offsite |
| Access control | None | IAM policies |

### Key Rotation Procedure
1. Generate new key
2. Create migration script to re-encrypt data
3. Update key in environment
4. Run migration
5. Verify all data accessible
6. Revoke old key

## 6. Authorization: RBAC + ABAC

### RBAC (Role-Based Access Control)

**Roles:**
| Role | Description | Permissions |
|------|-------------|-------------|
| `admin` | System administrator | All permissions |
| `researcher` | Regular user | Own resources only |

**Permission Matrix:**
```python
# app/core/authorization.py
ROLE_PERMISSIONS = {
    "admin": [
        "admin:manage",      # Admin dashboard
        "user:read",         # View all users
        "session:read:any",  # View any session
        "message:read:any",  # View any message
        "file:read:any",     # Access any file
    ],
    "researcher": [
        "session:read:own",  # Own sessions only
        "message:read:own",  # Own messages only
        "file:read:own",     # Own files only
    ],
}
```

### ABAC (Attribute-Based Access Control)

**Ownership Rules:**
- User chỉ truy cập resources do mình tạo
- Admin có thể truy cập tất cả

**Enforcement Functions:**
```python
def assert_session_access(session: ChatSession, user: User) -> None:
    """Raise 403 if user cannot access session."""

def assert_message_access(message: ChatMessage, user: User) -> None:
    """Raise 403 if user cannot access message."""

def assert_file_access(file: FileAttachment, user: User) -> None:
    """Raise 403 if user cannot access file."""
```

### Authorization Flow
```
Request → JWT Validation → Role Check → Ownership Check → Allow/Deny
            │               │              │
            ▼               ▼              ▼
         401 if          403 if        403 if
         invalid         no role       not owner
```

## 7. Admin Interface & Governance

### Admin Endpoints
| Endpoint | Purpose | Auth |
|----------|---------|------|
| `POST /auth/admin/promote` | Change user role | Admin only |
| `GET /admin/overview` | Dashboard stats | Admin only |
| `GET /admin/users` | User management | Admin only |

### Bootstrap Process
```python
# app/services/bootstrap.py
async def bootstrap_admin(db: AsyncSession):
    """Create admin user from env vars on startup."""
```

Environment variables:
- `ADMIN_EMAIL` (default: `admin@aira.local`)
- `ADMIN_PASSWORD` (default: `ChangeMe!123`)

> ⚠️ **Quan trọng:** Đổi mật khẩu admin mặc định ngay lập tức!

## 8. Security Checklist

### Before Demo
- [ ] Đổi JWT_SECRET_KEY
- [ ] Đổi ADMIN_PASSWORD
- [ ] Verify HTTPS active
- [ ] Test authorization rules

### Before Production
- [x] Enable rate limiting
- [ ] Setup WAF rules
- [x] Configure CORS properly
- [x] Enable security headers
- [ ] Setup intrusion detection
- [x] Implement audit logging
- [ ] Test penetration resistance
- [ ] Review all dependencies for vulnerabilities

### Ongoing
- [ ] Monitor failed login attempts
- [ ] Review access logs weekly
- [ ] Update dependencies monthly
- [ ] Rotate keys quarterly
- [ ] Conduct security audits annually

## 9. Threat Model

### Identified Threats

| Threat | Mitigation |
|--------|------------|
| Credential stuffing | Rate limiting, bcrypt cost factor |
| Session hijacking | Short token lifetime, HTTPS only |
| SQL injection | SQLAlchemy ORM, parameterized queries |
| XSS | API-only backend (no HTML rendering) |
| CSRF | JWT in Authorization header |
| Data breach | At-rest encryption |
| Man-in-the-middle | TLS + optional app-layer encryption |
| Privilege escalation | RBAC + ABAC enforcement |

### Trust Boundaries
```
┌──────────────────────────────────────────────────────────┐
│                    Internet (Untrusted)                  │
└───────────────────────────┬──────────────────────────────┘
                            │ TLS
┌───────────────────────────▼──────────────────────────────┐
│                    DMZ (Nginx)                           │
└───────────────────────────┬──────────────────────────────┘
                            │ Internal network
┌───────────────────────────▼──────────────────────────────┐
│                 Application (FastAPI)                    │
└───────────────────────────┬──────────────────────────────┘
                            │ Encrypted connection
┌───────────────────────────▼──────────────────────────────┐
│                 Database (Encrypted at-rest)             │
└──────────────────────────────────────────────────────────┘
```

## 10. Compliance Considerations

### GDPR
- User data encrypted at rest ✓
- Right to deletion (implement `DELETE /users/{id}`)
- Data portability (implement export feature)
- Consent tracking (add to user model)

### HIPAA (if handling medical research)
- End-to-end encryption ✓
- Access audit logs ✓
- BAA with cloud providers
- Data retention policies
