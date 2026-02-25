# Remediation Matrix

| Priority | Risk | Area | Owner | ETA | Action |
|---|---|---|---|---|---|
| P0 | High | Auth brute-force | Backend | 1 day | Enforce rate limiting on auth/chat/tools/upload |
| P0 | High | Privilege escalation | Backend | 1 day | Keep RBAC/ABAC checks + add regression tests |
| P0 | Medium | Health disclosure | Backend | 0.5 day | Keep `/health` minimal, hide sensitive internals |
| P1 | Medium | File upload spoofing | Backend | 1 day | MIME allowlist + PDF signature checks + filename sanitize |
| P1 | Medium | Admin actions traceability | Backend | 1 day | Add audit logs for promote/delete/storage actions |
| P1 | Medium | Browser security | Backend | 0.5 day | Add CSP, frame/referrer/content-type hardening headers |
| P1 | Medium | Cross-origin hardening | Backend | 0.5 day | Restrict CORS to allowlist env domains |
| P2 | Medium | LLM SDK lifecycle | Backend | 2 days | Migrate `google-generativeai` to `google.genai` |
| P2 | Medium | Key management | Backend/DevOps | 3 days | Key rotation + re-encryption migration job |
