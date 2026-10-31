"""Safe image fetching for post folders. Only allow-listed hosts, size-capped, sniffed."""

from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.domain import ImageAsset
from app.logging_config import log_event

ALLOWED_HOSTS = frozenset({"upload.wikimedia.org"})
_SIGNATURES = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}


def _extension(data: bytes) -> str | None:
    for signature, extension in _SIGNATURES.items():
        if data.startswith(signature):
            return extension
    return None


def fetch_image(url: str) -> bytes | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        log_event(30, "image_rejected", reason="host_not_allowed", host=parsed.hostname)
        return None
    with httpx.Client(timeout=settings.http_timeout_s * 2, headers={"User-Agent": settings.user_agent}) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > settings.max_image_bytes:
                    log_event(30, "image_rejected", reason="too_large")
                    return None
    return bytes(data)


def download_images(images: list[ImageAsset], folder: Path, limit: int = 3) -> list[ImageAsset]:
    """Download up to `limit` images into `folder`; returns only those that succeeded."""
    if not settings.download_images:
        return []
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[ImageAsset] = []
    for image in images:
        if len(saved) >= limit:
            break
        try:
            data = fetch_image(image.url)
        except Exception as exc:  # noqa: BLE001 - a missing image must not fail the article
            log_event(30, "image_download_failed", error=type(exc).__name__)
            continue
        extension = _extension(data) if data else None
        if not data or not extension:
            continue
        filename = f"image-{len(saved) + 1}{extension}"
        (folder / filename).write_bytes(data)
        saved.append(image.model_copy(update={"filename": filename}))
    log_event(20, "images_downloaded", requested=len(images), saved=len(saved))
    return saved
