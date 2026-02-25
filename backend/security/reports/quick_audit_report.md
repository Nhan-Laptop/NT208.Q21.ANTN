# AIRA Quick Security Audit Report

- Timestamp: `2026-02-14T02:52:04.967226+00:00`
- Target: `http://127.0.0.1:8000`
- Checks: `7`
- Passed: `7`
- Failed: `0`

## Findings

### PASS - health_info_disclosure
- Severity if failed: `MEDIUM`
- Details: /health should not expose sensitive implementation details.
- Evidence:
```json
{
  "status": 200,
  "keys": [
    "app",
    "status",
    "transport_encryption_enabled"
  ],
  "leaks": []
}
```

### PASS - idor_session_read
- Severity if failed: `HIGH`
- Details: User B must not read User A session.
- Evidence:
```json
{
  "status": 403,
  "body": "{\"detail\":\"You cannot access this session\"}"
}
```

### PASS - idor_message_list
- Severity if failed: `HIGH`
- Details: User B must not list User A messages.
- Evidence:
```json
{
  "status": 403,
  "body": "{\"detail\":\"You cannot access this session\"}"
}
```

### PASS - privilege_escalation_admin_overview
- Severity if failed: `HIGH`
- Details: Researcher must not access admin-only API.
- Evidence:
```json
{
  "status": 403,
  "body": "{\"detail\":\"Missing permissions: admin:manage\"}"
}
```

### PASS - encrypted_payload_tampering
- Severity if failed: `MEDIUM`
- Details: Tampered encrypted payload should fail gracefully with 400.
- Evidence:
```json
{
  "status": 400,
  "body": "{\"detail\":\"Invalid encrypted payload: Invalid encrypted payload length\"}"
}
```

### PASS - upload_pdf_magic_bytes
- Severity if failed: `MEDIUM`
- Details: Fake PDF should be rejected via signature check.
- Evidence:
```json
{
  "status": 415,
  "body": "{\"detail\":\"Invalid PDF file signature\"}"
}
```

### PASS - login_rate_limit
- Severity if failed: `HIGH`
- Details: Login endpoint should return 429 under brute-force attempts.
- Evidence:
```json
{
  "statuses": [
    401,
    401,
    401,
    401,
    401,
    401,
    429
  ]
}
```

## Remediation Matrix

| Priority | Area | Action |
|---|---|---|
| P0 | Auth | Enable strict rate limiting and monitor spikes |
| P0 | Authorization | Keep IDOR tests in CI regression suite |
| P1 | Upload | Enforce MIME + file signature checks |
| P1 | Crypto | Keep encrypted endpoint strict on payload/AAD errors |
| P1 | Observability | Record audit logs for admin/file actions |