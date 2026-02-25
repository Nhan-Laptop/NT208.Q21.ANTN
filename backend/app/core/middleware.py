from time import perf_counter

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.rate_limit import rate_limiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if not settings.security_headers_enabled:
            return response

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", settings.csp_policy)
        if settings.app_env.lower() in {"production", "staging"}:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        allowed, retry_after, bucket = rate_limiter.check(request)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "bucket": bucket,
                },
                headers={"Retry-After": str(retry_after)},
            )

        started = perf_counter()
        response = await call_next(request)
        elapsed_ms = int((perf_counter() - started) * 1000)
        response.headers.setdefault("X-Response-Time-Ms", str(elapsed_ms))
        return response
