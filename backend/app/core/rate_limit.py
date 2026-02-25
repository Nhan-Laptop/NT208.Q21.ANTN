import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock

from fastapi import Request

from app.core.config import settings

_CLEANUP_INTERVAL = 300  # purge expired entries every 5 minutes


@dataclass(slots=True)
class _Counter:
    window_start: float
    count: int


class InMemoryRateLimiter:
    """Simple fixed-window limiter for API hardening in single-instance deployments."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], _Counter] = {}
        self._lock = Lock()
        self._window_seconds = max(1, settings.rate_limit_window_seconds)
        self._last_cleanup = time.time()

    def _resolve_bucket(self, path: str) -> tuple[str, int]:
        base = settings.api_v1_str.rstrip("/")
        if path.startswith(f"{base}/auth/login") or path.startswith(f"{base}/auth/register"):
            return "auth", settings.rate_limit_auth_max
        if path.startswith(f"{base}/chat"):
            return "chat", settings.rate_limit_chat_max
        if path.startswith(f"{base}/tools"):
            return "tools", settings.rate_limit_tools_max
        if path.startswith(f"{base}/upload"):
            return "upload", settings.rate_limit_upload_max
        return "default", settings.rate_limit_default_max

    @staticmethod
    def _resolve_client(request: Request) -> str:
        """Resolve client IP — only trust X-Forwarded-For when behind a reverse proxy.

        For direct connections (development), always use the peer address.
        The first value in X-Forwarded-For is the original client only when set
        by a *trusted* proxy — we fall back to ``request.client.host`` as the
        most reliable identifier in deployments without a trusted proxy.
        """
        # Prefer the direct peer address to prevent header spoofing
        if request.client and request.client.host:
            return request.client.host
        # Fallback: if no peer (e.g. test client), try header
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or "unknown"

    def _maybe_cleanup(self, now: float) -> None:
        """Purge expired entries to prevent memory leak."""
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        expired_keys = [
            key for key, counter in self._store.items()
            if now - counter.window_start >= self._window_seconds
        ]
        for key in expired_keys:
            del self._store[key]

    def check(self, request: Request) -> tuple[bool, int, str]:
        """
        Returns: (allowed, retry_after_seconds, bucket)
        """
        if not settings.rate_limit_enabled:
            return True, 0, "disabled"

        if request.method.upper() == "OPTIONS":
            return True, 0, "preflight"

        bucket, limit = self._resolve_bucket(request.url.path)
        client = self._resolve_client(request)
        key = (bucket, client)
        now = time.time()

        with self._lock:
            self._maybe_cleanup(now)

            current = self._store.get(key)
            if current is None or now - current.window_start >= self._window_seconds:
                self._store[key] = _Counter(window_start=now, count=1)
                return True, 0, bucket

            if current.count >= limit:
                retry_after = int(self._window_seconds - (now - current.window_start))
                return False, max(retry_after, 1), bucket

            current.count += 1
            return True, 0, bucket


rate_limiter = InMemoryRateLimiter()
