import ipaddress
import socket
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from . import config


class InputError(ValueError):
    """Raised for bad user input; message is shown to the user."""


def validate_public_url(url: str) -> str:
    """Reject anything that isn't an http(s) URL pointing at a public address (SSRF guard)."""
    url = (url or "").strip()
    if not url:
        raise InputError("Enter a link to check.")
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise InputError("Only http and https links can be checked.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise InputError(f"Couldn't find the site {p.hostname}. Check the link for typos.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise InputError("That link points to a private network address and can't be fetched.")
    return url


# extension -> (kind, mime)
ALLOWED_FILES = {
    ".png": ("image", "image/png"), ".jpg": ("image", "image/jpeg"), ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"), ".gif": ("image", "image/gif"), ".bmp": ("image", "image/bmp"),
    ".pdf": ("document", "application/pdf"), ".docx": ("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".txt": ("document", "text/plain"), ".md": ("document", "text/plain"),
    ".mp3": ("audio", "audio/mpeg"), ".wav": ("audio", "audio/wav"), ".m4a": ("audio", "audio/mp4"),
    ".ogg": ("audio", "audio/ogg"), ".webm": ("audio", "audio/webm"), ".flac": ("audio", "audio/flac"),
    ".aac": ("audio", "audio/aac"),
    ".mp4": ("video", "video/mp4"), ".mov": ("video", "video/quicktime"), ".mkv": ("video", "video/x-matroska"),
    ".avi": ("video", "video/x-msvideo"),
}

_MAGIC = {
    "image": [b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8", b"BM"],
    "pdf": [b"%PDF"],
    "docx": [b"PK\x03\x04"],
}


def classify_upload(filename: str, head: bytes, size: int) -> tuple[str, str]:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_FILES:
        raise InputError(
            f"“{filename}” isn't a supported file. Use an image, PDF, Word (.docx), text, audio or video file."
        )
    if size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise InputError(f"Files must be under {config.MAX_UPLOAD_MB} MB.")
    if size == 0:
        raise InputError("That file is empty.")
    kind, mime = ALLOWED_FILES[ext]
    if ext == ".pdf" and not head.startswith(b"%PDF"):
        raise InputError("That file has a .pdf name but isn't a valid PDF.")
    if ext == ".docx" and not head.startswith(b"PK"):
        raise InputError("That file has a .docx name but isn't a valid Word document.")
    if kind == "image" and not any(head.startswith(m) for m in _MAGIC["image"]):
        raise InputError("That image file looks damaged or isn't really an image.")
    return kind, mime


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request):
        key = request.client.host if request.client else "anon"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, "Too many checks in a minute. Wait a moment and try again.")
        q.append(now)


verify_limiter = RateLimiter(config.RATE_LIMIT_PER_MIN)
