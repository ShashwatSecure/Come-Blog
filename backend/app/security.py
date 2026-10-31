"""API-key auth, sliding-window rate limiting and security headers."""

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.config import settings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
SITE_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> float | None:
        """Return None if allowed, else seconds until the caller may retry."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1.0, window - (now - hits[0]))
            hits.append(now)
            return None


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Declared as a security scheme so Swagger UI shows an "Authorize" button; auth itself is enforced below.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="Required only when COMEBLOG_API_KEY is set on the server.")


def require_api_key(supplied: str | None = Security(api_key_scheme)) -> None:
    """No-op when COMEBLOG_API_KEY is empty (local use); constant-time compare otherwise."""
    if not settings.api_key:
        return
    if not hmac.compare_digest((supplied or "").encode(), settings.api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def rate_limit(request: Request) -> None:
    retry = limiter.check(client_ip(request), settings.rate_limit_per_minute)
    if retry is not None:
        raise HTTPException(status_code=429, detail="Too many requests", headers={"Retry-After": str(int(retry))})
